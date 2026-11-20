#include "packing_engine.h"

#include <algorithm>
#include <cmath>
#include <functional>
#include <limits>
#include <stdexcept>
#include <string>

namespace binpack {

namespace {

// Coordinates are stored as 32-bit ints (twice the SIMD width of 64-bit).
// Half the range keeps every `position + extent` sum overflow free.
constexpr long kMaxCoord = std::numeric_limits<coord_t>::max() / 2;

coord_t toCoord(long value, const char* what) {
    if (value < 0 || value > kMaxCoord) {
        throw std::invalid_argument(std::string(what) + " must be between 0 and " +
                                    std::to_string(kMaxCoord) + ", got " + std::to_string(value));
    }
    return static_cast<coord_t>(value);
}

inline std::int64_t overlap1d(coord_t a0, coord_t a1, coord_t b0, coord_t b1) {
    return std::max<std::int64_t>(0, static_cast<std::int64_t>(std::min(a1, b1)) - std::max(a0, b0));
}

constexpr std::size_t kChunk = 64;  // collision test granularity (early exit per chunk)

// Shrinks the residual space of every extreme point that "sees" the new box
// [lo, hi) along +x, +y or +z, and flags points that stay usable (not inside
// the box and with room for an item of at least min_dim). Kept as a free
// function so the restrict-qualified parameters let the compiler vectorise it.
void shrinkResidualSpace(std::size_t n, const coord_t* __restrict px, const coord_t* __restrict py,
                         const coord_t* __restrict pz, coord_t* __restrict rx, coord_t* __restrict ry,
                         coord_t* __restrict rz, coord_t* __restrict live, const std::array<coord_t, 3>& lo,
                         const std::array<coord_t, 3>& hi, coord_t min_dim) {
    const coord_t lx = lo[0], ly = lo[1], lz = lo[2], hx = hi[0], hy = hi[1], hz = hi[2];
    for (std::size_t e = 0; e < n; ++e) {
        const bool inx = (lx <= px[e]) & (px[e] < hx);
        const bool iny = (ly <= py[e]) & (py[e] < hy);
        const bool inz = (lz <= pz[e]) & (pz[e] < hz);
        const coord_t nx = std::min(rx[e], (iny & inz & (lx >= px[e])) ? lx - px[e] : rx[e]);
        const coord_t ny = std::min(ry[e], (inx & inz & (ly >= py[e])) ? ly - py[e] : ry[e]);
        const coord_t nz = std::min(rz[e], (inx & iny & (lz >= pz[e])) ? lz - pz[e] : rz[e]);
        rx[e] = nx;
        ry[e] = ny;
        rz[e] = nz;
        live[e] = static_cast<coord_t>(!(inx & iny & inz) & (nx >= min_dim) & (ny >= min_dim) & (nz >= min_dim));
    }
}

}  // namespace

// ---------------------------------------------------------------- ItemSpec --

ItemSpec ItemSpec::fromItem(const Item& item) {
    ItemSpec spec;
    for (RotationType r : item.getEffectiveRotations()) {
        const auto d = rotatedDimensions(item.getWidth(), item.getHeight(), item.getDepth(), r);
        const std::array<coord_t, 3> dims = {toCoord(d[0], "item dimension"),
                                             toCoord(d[1], "item dimension"),
                                             toCoord(d[2], "item dimension")};
        const bool duplicate = std::any_of(spec.orientations.begin(), spec.orientations.end(),
                                           [&](const Orientation& o) { return o.dims == dims; });
        if (!duplicate) {
            spec.orientations.push_back({r, dims});
        }
    }
    spec.weight = item.weight;
    spec.bottom_only = item.isBottomLoadOnlyEnabled();
    spec.no_stack = item.isDisableStackingEnabled() || item.isHeightConstrained();
    spec.max_stack_height = toCoord(std::max(0L, item.getStuffingHeight()), "stuffing height");
    spec.max_stack_weight = std::max(0.0f, item.getStuffingMaxWeight());
    spec.max_stack_layers = std::max(0, item.getStuffingLayers());
    return spec;
}

coord_t ItemSpec::minDimension() const {
    coord_t m = std::numeric_limits<coord_t>::max();
    for (const auto& o : orientations) {
        m = std::min({m, o.dims[0], o.dims[1], o.dims[2]});
    }
    return m;
}

bool ItemSpec::operator==(const ItemSpec& other) const {
    if (orientations.size() != other.orientations.size()) return false;
    for (std::size_t i = 0; i < orientations.size(); ++i) {
        if (orientations[i].dims != other.orientations[i].dims ||
            orientations[i].rotation != other.orientations[i].rotation) {
            return false;
        }
    }
    return weight == other.weight && bottom_only == other.bottom_only && no_stack == other.no_stack &&
           max_stack_height == other.max_stack_height && max_stack_weight == other.max_stack_weight &&
           max_stack_layers == other.max_stack_layers;
}

// --------------------------------------------------------- ContainerEngine --

ContainerEngine::ContainerEngine(long width, long height, long depth, float max_weight,
                                 const PackingConfig& config, double flush_bonus)
    : size_{toCoord(width, "bin width"), toCoord(height, "bin height"), toCoord(depth, "bin depth")},
      max_weight_(max_weight),
      config_(config),
      axes_(fillOrderAxes(config.fill_order)),
      flush_bonus_(flush_bonus) {
    // A single extreme point in the origin corner.
    for (int a = 0; a < 3; ++a) {
        ep_[a].push_back(0);
        rs_[a].push_back(size_[a]);
    }
    witness_.push_back(kNoWitness);
    ep_level_.push_back(levelId(0));
}

bool ContainerEngine::keyLess(const coord_t* a, const coord_t* b) const {
    for (int k = 0; k < 3; ++k) {
        const int axis = axes_[k];
        if (a[axis] != b[axis]) return a[axis] < b[axis];
    }
    return false;
}

// Branch-free, auto-vectorised interior overlap test against all placed boxes.
// Recently placed boxes are the most likely to collide, so chunks are scanned
// newest first and the scan stops at the first chunk with a hit.
bool ContainerEngine::boxIntersects(std::uint32_t i, const std::array<coord_t, 3>& lo,
                                    const std::array<coord_t, 3>& hi) const {
    return lo_[0][i] < hi[0] && lo[0] < hi_[0][i] && lo_[1][i] < hi[1] && lo[1] < hi_[1][i] &&
           lo_[2][i] < hi[2] && lo[2] < hi_[2][i];
}

std::int64_t ContainerEngine::findCollision(const std::array<coord_t, 3>& lo, const std::array<coord_t, 3>& hi) const {
    const std::size_t n = weight_.size();
    const coord_t* __restrict x0 = lo_[0].data();
    const coord_t* __restrict y0 = lo_[1].data();
    const coord_t* __restrict z0 = lo_[2].data();
    const coord_t* __restrict x1 = hi_[0].data();
    const coord_t* __restrict y1 = hi_[1].data();
    const coord_t* __restrict z1 = hi_[2].data();
    const coord_t cx0 = lo[0], cy0 = lo[1], cz0 = lo[2];
    const coord_t cx1 = hi[0], cy1 = hi[1], cz1 = hi[2];

    std::size_t end = n;
    while (end > 0) {
        const std::size_t begin = end > kChunk ? end - kChunk : 0;
        int hit = 0;
        for (std::size_t i = begin; i < end; ++i) {
            hit |= static_cast<int>(x0[i] < cx1) & static_cast<int>(cx0 < x1[i]) &
                   static_cast<int>(y0[i] < cy1) & static_cast<int>(cy0 < y1[i]) &
                   static_cast<int>(z0[i] < cz1) & static_cast<int>(cz0 < z1[i]);
        }
        if (hit) {
            for (std::size_t i = end; i-- > begin;) {
                if (boxIntersects(static_cast<std::uint32_t>(i), lo, hi)) return static_cast<std::int64_t>(i);
            }
        }
        end = begin;
    }
    return -1;
}

// Enough of the item's base must rest on the floor or on box tops at its height.
std::uint32_t ContainerEngine::levelId(coord_t y) {
    const auto [it, inserted] = level_of_.try_emplace(y, static_cast<std::uint32_t>(levels_.size()));
    if (inserted) levels_.emplace_back();
    return it->second;
}

bool ContainerEngine::supported(const std::array<coord_t, 3>& lo, const std::array<coord_t, 3>& hi,
                                std::uint32_t level) const {
    if (lo[1] == 0 || config_.min_support_ratio <= 0.0) return true;
    const std::int64_t area = static_cast<std::int64_t>(hi[0] - lo[0]) * (hi[2] - lo[2]);
    if (area == 0) return true;
    const std::vector<std::uint32_t>& tops = levels_[level];
    if (tops.empty()) return false;

    const double needed = config_.min_support_ratio * static_cast<double>(area) - 1e-9;
    std::int64_t support = 0;
    for (const std::uint32_t i : tops) {
        support += overlap1d(lo[0], hi[0], lo_[0][i], hi_[0][i]) * overlap1d(lo[2], hi[2], lo_[2][i], hi_[2][i]);
        if (static_cast<double>(support) >= needed) return true;
    }
    return false;
}

// Stacking rules of boxes below the candidate (no stacking, max height/weight/layers).
bool ContainerEngine::rulesBelowAllow(const std::array<coord_t, 3>& lo, const std::array<coord_t, 3>& hi,
                                      const ItemSpec& spec) const {
    if (rules_.empty()) return true;
    const double base = static_cast<double>(hi[0] - lo[0]) * static_cast<double>(hi[2] - lo[2]);
    for (const StackRule& rule : rules_) {
        const std::uint32_t i = rule.box;
        if (hi_[1][i] > lo[1]) continue;  // not below the candidate
        const std::int64_t ov = overlap1d(lo[0], hi[0], lo_[0][i], hi_[0][i]) *
                                overlap1d(lo[2], hi[2], lo_[2][i], hi_[2][i]);
        if (ov <= 0) continue;
        if (rule.no_stack) return false;
        if (hi[1] > rule.max_top) return false;
        if (rule.max_load > 0.0f && base > 0.0) {
            const double share = spec.weight * (static_cast<double>(ov) / base);
            if (rule.load + share > rule.max_load + 1e-6) return false;
        }
        if (rule.max_layers > 0 &&
            std::find(rule.levels.begin(), rule.levels.end(), lo[1]) == rule.levels.end() &&
            static_cast<int>(rule.levels.size()) + 1 > rule.max_layers) {
            return false;
        }
    }
    return true;
}

// The candidate's own stacking rules against boxes that already sit above it
// (possible when an item is slid underneath an overhang).
bool ContainerEngine::ownRuleAllows(const std::array<coord_t, 3>& lo, const std::array<coord_t, 3>& hi,
                                    const ItemSpec& spec) const {
    const coord_t max_top = spec.max_stack_height > 0 ? hi[1] + spec.max_stack_height
                                                      : std::numeric_limits<coord_t>::max();
    double load = 0.0;
    std::vector<coord_t> levels;
    for (std::size_t i = 0; i < weight_.size(); ++i) {
        if (lo_[1][i] < hi[1]) continue;
        const std::int64_t ov = overlap1d(lo[0], hi[0], lo_[0][i], hi_[0][i]) *
                                overlap1d(lo[2], hi[2], lo_[2][i], hi_[2][i]);
        if (ov <= 0) continue;
        if (spec.no_stack || hi_[1][i] > max_top) return false;
        const double area = static_cast<double>(hi_[0][i] - lo_[0][i]) * (hi_[2][i] - lo_[2][i]);
        if (area > 0) load += weight_[i] * (static_cast<double>(ov) / area);
        if (std::find(levels.begin(), levels.end(), lo_[1][i]) == levels.end()) levels.push_back(lo_[1][i]);
    }
    if (spec.max_stack_weight > 0.0f && load > spec.max_stack_weight + 1e-6) return false;
    if (spec.max_stack_layers > 0 && static_cast<int>(levels.size()) > spec.max_stack_layers) return false;
    return true;
}

bool ContainerEngine::feasible(std::size_t ep, const std::array<coord_t, 3>& d, const ItemSpec& spec) const {
    const std::array<coord_t, 3> p = {ep_[0][ep], ep_[1][ep], ep_[2][ep]};
    const std::array<coord_t, 3> hi = {p[0] + d[0], p[1] + d[1], p[2] + d[2]};
    if (hi[0] > size_[0] || hi[1] > size_[1] || hi[2] > size_[2]) return false;
    // Cheapest checks first; the O(n) collision scan runs last.
    if (witness_[ep] != kNoWitness && boxIntersects(witness_[ep], p, hi)) return false;
    if (!supported(p, hi, ep_level_[ep])) return false;
    if (!rulesBelowAllow(p, hi, spec)) return false;
    const std::int64_t hit = findCollision(p, hi);
    if (hit >= 0) {
        witness_[ep] = static_cast<std::uint32_t>(hit);
        return false;
    }
    if (spec.hasStackingRules() && !ownRuleAllows(p, hi, spec)) return false;
    return true;
}

// Lower is better: how much of the free space along each axis is left over when
// the orientation is repeated until the next obstacle ("tiling waste").
double ContainerEngine::orientationScore(std::size_t ep, const std::array<coord_t, 3>& d) const {
    double score = 0.0;
    for (int a = 0; a < 3; ++a) {
        const coord_t free = rs_[a][ep];
        if (free > 0 && d[a] > 0) {
            score += static_cast<double>(free % d[a]) / free;
        }
    }
    // Flush with an existing wall front / layer top along the primary fill
    // axis: keeps walls and layers even, so the next one starts on a flat face.
    const int a0 = axes_[0];
    if (flush_bonus_ > 0.0 && primary_faces_.count(ep_[a0][ep] + d[a0]) != 0) {
        score -= flush_bonus_;
    }
    return score;
}

bool ContainerEngine::findPlacement(const ItemSpec& spec, Placement& out) const {
    if (spec.orientations.empty()) return false;
    if (max_weight_ > 0.0f && total_weight_ + spec.weight > max_weight_ + 1e-6f) return false;

    // Non-stackable items go as high as possible: nothing may be above them
    // anyway, so this wastes the least space and keeps them on top of the load.
    const bool prefer_high = config_.non_stackable_on_top && spec.no_stack;

    bool found = false;
    coord_t best_y = -1;
    const std::size_t n = ep_[0].size();
    for (std::size_t e = 0; e < n; ++e) {
        const std::array<coord_t, 3> p = {ep_[0][e], ep_[1][e], ep_[2][e]};
        if (spec.bottom_only && p[1] != 0) continue;
        if (prefer_high && found && p[1] <= best_y) continue;

        int best = -1;
        double best_score = 0.0;
        for (std::size_t o = 0; o < spec.orientations.size(); ++o) {
            const auto& d = spec.orientations[o].dims;
            // Residual space rejects most candidates without touching the boxes.
            if (d[0] > rs_[0][e] || d[1] > rs_[1][e] || d[2] > rs_[2][e]) continue;
            if (!feasible(e, d, spec)) continue;
            const double score = orientationScore(e, d);
            // Ties: keep the lower (more stable) orientation, then the earlier one.
            if (best < 0 || score < best_score - 1e-9 ||
                (score <= best_score + 1e-9 && d[1] < spec.orientations[best].dims[1])) {
                best = static_cast<int>(o);
                best_score = score;
            }
        }
        if (best >= 0) {
            out.position = p;
            out.dims = spec.orientations[best].dims;
            out.rotation = spec.orientations[best].rotation;
            found = true;
            best_y = p[1];
            // Extreme points are sorted by fill order: the first hit is the answer.
            if (!prefer_high) return true;
        }
    }
    return found;
}

void ContainerEngine::commit(const ItemSpec& spec, const Placement& placement) {
    const auto idx = static_cast<std::uint32_t>(weight_.size());
    for (int a = 0; a < 3; ++a) {
        lo_[a].push_back(placement.position[a]);
        hi_[a].push_back(placement.position[a] + placement.dims[a]);
    }
    weight_.push_back(spec.weight);
    total_weight_ += spec.weight;
    levels_[levelId(hi_[1][idx])].push_back(idx);
    ++primary_faces_[hi_[axes_[0]][idx]];

    const std::array<coord_t, 3> lo = placement.position;
    const std::array<coord_t, 3> hi = {lo[0] + placement.dims[0], lo[1] + placement.dims[1], lo[2] + placement.dims[2]};
    const double base = static_cast<double>(placement.dims[0]) * placement.dims[2];

    // The new box loads every rule-carrying box below it.
    for (StackRule& rule : rules_) {
        const std::uint32_t i = rule.box;
        if (hi_[1][i] > lo[1]) continue;
        const std::int64_t ov = overlap1d(lo[0], hi[0], lo_[0][i], hi_[0][i]) *
                                overlap1d(lo[2], hi[2], lo_[2][i], hi_[2][i]);
        if (ov <= 0) continue;
        if (base > 0) rule.load += static_cast<float>(spec.weight * (static_cast<double>(ov) / base));
        if (std::find(rule.levels.begin(), rule.levels.end(), lo[1]) == rule.levels.end()) {
            rule.levels.push_back(lo[1]);
        }
    }

    if (spec.hasStackingRules()) {
        StackRule rule;
        rule.box = idx;
        rule.no_stack = spec.no_stack;
        rule.max_top = spec.max_stack_height > 0 ? hi[1] + spec.max_stack_height
                                                 : std::numeric_limits<coord_t>::max();
        rule.max_load = spec.max_stack_weight;
        rule.max_layers = spec.max_stack_layers;
        // Account for boxes that already sit above (pre-placed items).
        for (std::uint32_t i = 0; i < idx; ++i) {
            if (lo_[1][i] < hi[1]) continue;
            const std::int64_t ov = overlap1d(lo[0], hi[0], lo_[0][i], hi_[0][i]) *
                                    overlap1d(lo[2], hi[2], lo_[2][i], hi_[2][i]);
            if (ov <= 0) continue;
            const double area = static_cast<double>(hi_[0][i] - lo_[0][i]) * (hi_[2][i] - lo_[2][i]);
            if (area > 0) rule.load += static_cast<float>(weight_[i] * (static_cast<double>(ov) / area));
            if (std::find(rule.levels.begin(), rule.levels.end(), lo_[1][i]) == rule.levels.end()) {
                rule.levels.push_back(lo_[1][i]);
            }
        }
        rules_.push_back(std::move(rule));
    }

    updateExtremePoints(idx);
}

bool ContainerEngine::containsPoint(const std::array<coord_t, 3>& p) const {
    const std::size_t n = weight_.size();
    const coord_t *x0 = lo_[0].data(), *y0 = lo_[1].data(), *z0 = lo_[2].data();
    const coord_t *x1 = hi_[0].data(), *y1 = hi_[1].data(), *z1 = hi_[2].data();
    int inside = 0;
    for (std::size_t i = 0; i < n; ++i) {
        inside |= static_cast<int>(x0[i] <= p[0]) & static_cast<int>(p[0] < x1[i]) &
                  static_cast<int>(y0[i] <= p[1]) & static_cast<int>(p[1] < y1[i]) &
                  static_cast<int>(z0[i] <= p[2]) & static_cast<int>(p[2] < z1[i]);
    }
    return inside != 0;
}

// Free distance from p along +axis until a box face or the bin wall.
coord_t ContainerEngine::castRay(const std::array<coord_t, 3>& p, int axis) const {
    const int b = (axis + 1) % 3, c = (axis + 2) % 3;
    const std::size_t n = weight_.size();
    const coord_t* __restrict la = lo_[axis].data();
    const coord_t* __restrict lb = lo_[b].data();
    const coord_t* __restrict lc = lo_[c].data();
    const coord_t* __restrict hb = hi_[b].data();
    const coord_t* __restrict hc = hi_[c].data();
    const coord_t pa = p[axis], pb = p[b], pc = p[c];
    constexpr coord_t kNone = std::numeric_limits<coord_t>::max();
    coord_t stop = size_[axis];
    for (std::size_t i = 0; i < n; ++i) {  // plain min-reduction: vectorises
        const bool hit = (lb[i] <= pb) & (pb < hb[i]) & (lc[i] <= pc) & (pc < hc[i]) & (la[i] >= pa);
        stop = std::min(stop, hit ? la[i] : kNone);
    }
    return stop - pa;
}

// Coordinate reached when sliding p along -axis until a box face or the wall.
coord_t ContainerEngine::projectBack(const std::array<coord_t, 3>& p, int axis) const {
    const int b = (axis + 1) % 3, c = (axis + 2) % 3;
    const std::size_t n = weight_.size();
    const coord_t* __restrict ha = hi_[axis].data();
    const coord_t* __restrict lb = lo_[b].data();
    const coord_t* __restrict lc = lo_[c].data();
    const coord_t* __restrict hb = hi_[b].data();
    const coord_t* __restrict hc = hi_[c].data();
    const coord_t pa = p[axis], pb = p[b], pc = p[c];
    coord_t stop = 0;
    for (std::size_t i = 0; i < n; ++i) {  // plain max-reduction: vectorises
        const bool hit = (lb[i] <= pb) & (pb < hb[i]) & (lc[i] <= pc) & (pc < hc[i]) & (ha[i] <= pa);
        stop = std::max(stop, hit ? ha[i] : coord_t{0});
    }
    return stop;
}

void ContainerEngine::updateExtremePoints(std::uint32_t box) {
    const std::array<coord_t, 3> lo = {lo_[0][box], lo_[1][box], lo_[2][box]};
    const std::array<coord_t, 3> hi = {hi_[0][box], hi_[1][box], hi_[2][box]};
    const coord_t min_dim = min_item_dim_;

    // 1) Shrink the residual space of existing points (vectorised pass) and
    //    mark points swallowed by the new box or too cramped for any item.
    const std::size_t n = ep_[0].size();
    std::vector<coord_t> alive(n);
    shrinkResidualSpace(n, ep_[0].data(), ep_[1].data(), ep_[2].data(), rs_[0].data(), rs_[1].data(),
                        rs_[2].data(), alive.data(), lo, hi, min_dim);

    // 2) New candidates: the three corners of the box plus their projections
    //    onto the nearest surfaces (Crainic et al.), e.g. the right-bottom
    //    corner dropped down onto whatever is below it.
    const std::array<coord_t, 3> corner_x = {hi[0], lo[1], lo[2]};
    const std::array<coord_t, 3> corner_y = {lo[0], hi[1], lo[2]};
    const std::array<coord_t, 3> corner_z = {lo[0], lo[1], hi[2]};
    std::vector<std::array<coord_t, 3>> candidates = {corner_x, corner_y, corner_z};
    auto add_projection = [&](std::array<coord_t, 3> p, int axis) {
        p[axis] = projectBack(p, axis);
        candidates.push_back(p);
    };
    add_projection(corner_x, 1);
    add_projection(corner_x, 2);
    add_projection(corner_y, 0);
    add_projection(corner_y, 2);
    add_projection(corner_z, 0);
    add_projection(corner_z, 1);

    std::vector<std::array<coord_t, 6>> fresh;  // x, y, z, rx, ry, rz
    for (const auto& p : candidates) {
        if (p[0] >= size_[0] || p[1] >= size_[1] || p[2] >= size_[2]) continue;
        bool duplicate = false;
        for (const auto& f : fresh) {
            if (f[0] == p[0] && f[1] == p[1] && f[2] == p[2]) { duplicate = true; break; }
        }
        if (duplicate) continue;
        const std::array<coord_t, 3> r = {castRay(p, 0), castRay(p, 1), castRay(p, 2)};
        if (r[0] < min_dim || r[1] < min_dim || r[2] < min_dim) continue;
        if (containsPoint(p)) continue;  // rays cannot tell if p is already inside a box
        fresh.push_back({p[0], p[1], p[2], r[0], r[1], r[2]});
    }
    std::sort(fresh.begin(), fresh.end(), [this](const auto& a, const auto& b) { return keyLess(a.data(), b.data()); });

    // 3) Merge surviving points with the new ones, keeping fill-order sorting
    //    and dropping duplicates.
    std::array<std::vector<coord_t>, 3> ep, rs;
    std::vector<std::uint32_t> witness, level;
    for (int a = 0; a < 3; ++a) {
        ep[a].reserve(n + fresh.size());
        rs[a].reserve(n + fresh.size());
    }
    witness.reserve(n + fresh.size());
    level.reserve(n + fresh.size());
    auto push = [&](const coord_t* p, const coord_t* r, std::uint32_t w, std::uint32_t l) {
        const std::size_t m = ep[0].size();
        if (m > 0 && ep[0][m - 1] == p[0] && ep[1][m - 1] == p[1] && ep[2][m - 1] == p[2]) return;
        for (int a = 0; a < 3; ++a) {
            ep[a].push_back(p[a]);
            rs[a].push_back(r[a]);
        }
        witness.push_back(w);
        level.push_back(l);
    };
    std::size_t e = 0, f = 0;
    while (e < n || f < fresh.size()) {
        if (e < n && !alive[e]) { ++e; continue; }
        const coord_t old_p[3] = {e < n ? ep_[0][e] : 0, e < n ? ep_[1][e] : 0, e < n ? ep_[2][e] : 0};
        const bool take_old = f >= fresh.size() || (e < n && !keyLess(fresh[f].data(), old_p));
        if (take_old) {
            const coord_t r[3] = {rs_[0][e], rs_[1][e], rs_[2][e]};
            push(old_p, r, witness_[e], ep_level_[e]);
            ++e;
        } else {
            push(fresh[f].data(), fresh[f].data() + 3, kNoWitness, levelId(fresh[f][1]));
            ++f;
        }
    }
    ep_ = std::move(ep);
    rs_ = std::move(rs);
    witness_ = std::move(witness);
    ep_level_ = std::move(level);
}

}  // namespace binpack
