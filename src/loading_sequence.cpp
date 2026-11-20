#include "loading_sequence.h"

#include <algorithm>
#include <cstdint>
#include <queue>
#include <tuple>

namespace binpack {

namespace {

inline bool overlaps(coord_t a0, coord_t a1, coord_t b0, coord_t b1) {
    return a0 < b1 && b0 < a1;
}

// `a` carries `b`: b's bottom touches a's top over a non-empty area.
inline bool supports(const SequenceBox& a, const SequenceBox& b) {
    return a.hi[1] == b.lo[1] && overlaps(a.lo[0], a.hi[0], b.lo[0], b.hi[0]) &&
           overlaps(a.lo[2], a.hi[2], b.lo[2], b.hi[2]);
}

// `b` lies in the straight path from `a` to the access side, so `a` must be
// loaded first.
inline bool inAccessPath(const SequenceBox& a, const SequenceBox& b, LoadingAccess access) {
    switch (access) {
        case LoadingAccess::Door:
            return b.lo[2] >= a.hi[2] && overlaps(a.lo[0], a.hi[0], b.lo[0], b.hi[0]) &&
                   overlaps(a.lo[1], a.hi[1], b.lo[1], b.hi[1]);
        case LoadingAccess::Top:
            return b.lo[1] >= a.hi[1] && overlaps(a.lo[0], a.hi[0], b.lo[0], b.hi[0]) &&
                   overlaps(a.lo[2], a.hi[2], b.lo[2], b.hi[2]);
        case LoadingAccess::RightSide:
            return b.lo[0] >= a.hi[0] && overlaps(a.lo[1], a.hi[1], b.lo[1], b.hi[1]) &&
                   overlaps(a.lo[2], a.hi[2], b.lo[2], b.hi[2]);
        case LoadingAccess::LeftSide:
            return b.hi[0] <= a.lo[0] && overlaps(a.lo[1], a.hi[1], b.lo[1], b.hi[1]) &&
                   overlaps(a.lo[2], a.hi[2], b.lo[2], b.hi[2]);
        case LoadingAccess::None:
            return false;
    }
    return false;
}

inline bool hasVolume(const SequenceBox& b) {
    return b.hi[0] > b.lo[0] && b.hi[1] > b.lo[1] && b.hi[2] > b.lo[2];
}

// Zero-volume items (e.g. sizes rounded to 0) take no space: they neither
// block nor carry anything, and coincident ones would otherwise form cycles.
inline bool mustPrecede(const SequenceBox& a, const SequenceBox& b, LoadingAccess access) {
    return hasVolume(a) && hasVolume(b) && (supports(a, b) || inAccessPath(a, b, access));
}

using Key = std::tuple<std::int64_t, std::int64_t, std::int64_t>;

// Loading preference: deepest along the access direction first, then bottom-up.
Key sequenceKey(const SequenceBox& b, LoadingAccess access, const std::array<int, 3>& fill_axes) {
    switch (access) {
        case LoadingAccess::Door: return {b.lo[2], b.lo[1], b.lo[0]};
        case LoadingAccess::Top: return {b.lo[1], b.lo[2], b.lo[0]};
        case LoadingAccess::RightSide: return {b.lo[0], b.lo[1], b.lo[2]};
        case LoadingAccess::LeftSide: return {-static_cast<std::int64_t>(b.hi[0]), b.lo[1], b.lo[2]};
        case LoadingAccess::None: break;
    }
    return {b.lo[fill_axes[0]], b.lo[fill_axes[1]], b.lo[fill_axes[2]]};
}

double supportRatio(const std::vector<SequenceBox>& boxes, const std::vector<char>& active, std::size_t j) {
    const SequenceBox& b = boxes[j];
    const double area = static_cast<double>(b.hi[0] - b.lo[0]) * static_cast<double>(b.hi[2] - b.lo[2]);
    if (b.lo[1] == 0 || area <= 0.0) return 1.0;
    double supported = 0.0;
    for (std::size_t i = 0; i < boxes.size(); ++i) {
        if (!active[i] || i == j || boxes[i].hi[1] != b.lo[1]) continue;
        const double ox = std::max(0, std::min(b.hi[0], boxes[i].hi[0]) - std::max(b.lo[0], boxes[i].lo[0]));
        const double oz = std::max(0, std::min(b.hi[2], boxes[i].hi[2]) - std::max(b.lo[2], boxes[i].lo[2]));
        supported += ox * oz;
    }
    return supported / area;
}

}  // namespace

SequencePlan planLoadingSequence(const std::vector<SequenceBox>& boxes, LoadingAccess access,
                                 FillOrder fill_order, double min_support_ratio) {
    const std::size_t n = boxes.size();
    const std::array<int, 3> fill_axes = fillOrderAxes(fill_order);

    // Precedence edges (i before j) are evaluated on the fly: storing them can
    // take O(n^2) memory for long, narrow loads.
    auto precedes = [&](std::size_t i, std::size_t j) { return i != j && mustPrecede(boxes[i], boxes[j], access); };

    std::vector<Key> keys(n);
    for (std::size_t i = 0; i < n; ++i) keys[i] = sequenceKey(boxes[i], access, fill_axes);
    auto later = [&keys](std::uint32_t a, std::uint32_t b) {
        return keys[a] != keys[b] ? keys[a] > keys[b] : a > b;
    };

    SequencePlan plan;
    std::vector<char> active(n, 1);
    for (;;) {
        // Kahn's algorithm, always taking the preferred box among the loadable ones.
        std::vector<std::size_t> pending(n, 0);
        std::size_t active_count = 0;
        for (std::size_t j = 0; j < n; ++j) {
            if (!active[j]) continue;
            ++active_count;
            for (std::size_t i = 0; i < n; ++i) pending[j] += (active[i] && precedes(i, j)) ? 1 : 0;
        }
        std::priority_queue<std::uint32_t, std::vector<std::uint32_t>, decltype(later)> ready(later);
        for (std::size_t j = 0; j < n; ++j) {
            if (active[j] && pending[j] == 0) ready.push(static_cast<std::uint32_t>(j));
        }
        std::vector<char> done(n, 0);
        plan.order.clear();
        while (!ready.empty()) {
            const std::uint32_t i = ready.top();
            ready.pop();
            done[i] = 1;
            plan.order.push_back(i);
            for (std::size_t j = 0; j < n; ++j) {
                if (active[j] && !done[j] && precedes(i, j) && --pending[j] == 0) {
                    ready.push(static_cast<std::uint32_t>(j));
                }
            }
        }
        if (plan.order.size() == active_count) return plan;

        // Every stuck box has a stuck predecessor: walking backwards must close a cycle.
        std::size_t start = 0;
        while (!(active[start] && !done[start])) ++start;
        std::vector<std::size_t> walk;
        std::vector<std::size_t> seen_at(n, SIZE_MAX);
        std::size_t cur = start;
        while (seen_at[cur] == SIZE_MAX) {
            seen_at[cur] = walk.size();
            walk.push_back(cur);
            for (std::size_t p = 0; p < n; ++p) {
                if (active[p] && !done[p] && precedes(p, cur)) { cur = p; break; }
            }
        }
        const std::vector<std::size_t> cycle(walk.begin() + static_cast<std::ptrdiff_t>(seen_at[cur]), walk.end());

        // Take out the most recently placed movable box of the cycle.
        std::size_t victim = SIZE_MAX;
        for (std::size_t c : cycle) {
            if (!boxes[c].fixed && (victim == SIZE_MAX || c > victim)) victim = c;
        }
        if (victim == SIZE_MAX) {
            // Only fixed boxes: report, and list the rest in preference order.
            plan.feasible = false;
            std::vector<std::uint32_t> rest;
            for (std::size_t j = 0; j < n; ++j) {
                if (active[j] && !done[j]) rest.push_back(static_cast<std::uint32_t>(j));
            }
            std::sort(rest.begin(), rest.end(), [&](std::uint32_t a, std::uint32_t b) { return later(b, a); });
            plan.order.insert(plan.order.end(), rest.begin(), rest.end());
            return plan;
        }

        // Remove it, and anything that no longer has enough support.
        std::vector<std::size_t> queue = {victim};
        active[victim] = 0;
        plan.removed.push_back(victim);
        while (!queue.empty()) {
            const std::size_t r = queue.back();
            queue.pop_back();
            for (std::size_t j = 0; j < n; ++j) {
                if (!active[j] || boxes[j].fixed || !supports(boxes[r], boxes[j])) continue;
                if (min_support_ratio > 0.0 && supportRatio(boxes, active, j) + 1e-9 < min_support_ratio) {
                    active[j] = 0;
                    plan.removed.push_back(j);
                    queue.push_back(j);
                }
            }
        }
    }
}

std::string SequenceViolation::describe() const {
    const std::string s = "step " + std::to_string(step + 1);
    const std::string o = "step " + std::to_string(other + 1);
    if (kind == Kind::NotSupported) return s + " rests on " + o + ", which is loaded later";
    return s + " cannot be reached: its path from the loading side is blocked by " + o;
}

std::vector<SequenceViolation> checkLoadingSequence(const std::vector<SequenceBox>& boxes, LoadingAccess access) {
    std::vector<SequenceViolation> violations;
    for (std::size_t k = 0; k < boxes.size(); ++k) {
        if (!hasVolume(boxes[k])) continue;
        for (std::size_t m = 0; m < boxes.size(); ++m) {
            if (!hasVolume(boxes[m])) continue;
            if (m < k && inAccessPath(boxes[k], boxes[m], access)) {
                violations.push_back({k, m, SequenceViolation::Kind::PathBlocked});
            } else if (m > k && supports(boxes[m], boxes[k])) {
                violations.push_back({k, m, SequenceViolation::Kind::NotSupported});
            }
        }
    }
    return violations;
}

}  // namespace binpack
