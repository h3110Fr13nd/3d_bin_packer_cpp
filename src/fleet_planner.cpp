// fleet_planner.cpp - which containers to book, and what goes into each.
//
// Construction: containers are opened one at a time. For every container type
// still available, the remaining cargo is packed into an empty container of
// that type, and the type doing the most work per cost is opened (or, when one
// container can take everything that is left, the cheapest such one). Several
// rules are run (best ratio, biggest first, one per type "use this type first")
// and each result is improved:
//   * eliminate - empty a lightly loaded container into the others,
//   * merge     - replace two containers by one (of any type) holding both loads,
//   * downsize  - move a load into a cheaper / smaller container type,
//   * fill      - put unshipped cargo into spare space or extra containers,
//   * (Profit)  - drop containers whose cargo is worth less than they cost.
// The best fleet wins: most cargo (by priority, then objective), then cheapest
// (or fewest containers), then the least container volume.
#include "fleet_planner.h"

#include <algorithm>
#include <cmath>
#include <functional>
#include <limits>
#include <map>
#include <numeric>
#include <set>
#include <string>
#include <utility>

namespace binpack {

namespace {

bool close(double a, double b) {
    return std::abs(a - b) <= 1e-9 * std::max({1.0, std::abs(a), std::abs(b)});
}

struct Solution {
    std::vector<FleetContainer> containers;
    std::vector<Item*> rest;
};

std::vector<Item*> itemsOf(const BinPlan& plan) {
    std::vector<Item*> items;
    items.reserve(plan.placed.size());
    for (const auto& [item, p] : plan.placed) items.push_back(item);
    return items;
}

class FleetPlanner {
public:
    FleetPlanner(const std::vector<Item*>& items, const std::vector<FleetType>& types, const PackingConfig& config)
        : types_(types), full_(config), quick_(config) {
        quick_.optimize = false;
        // Items that fit no container type at all can never be shipped - nor
        // can the rest of their consignment.
        std::set<std::string> dead_groups;
        std::vector<char> fits(items.size());
        for (std::size_t i = 0; i < items.size(); ++i) {
            fits[i] = std::any_of(types.begin(), types.end(), [&](const FleetType& t) {
                return t.available != 0 && fitsEmptyBin(*items[i], *t.bin);
            });
            if (!fits[i] && !items[i]->group.empty()) dead_groups.insert(items[i]->group);
        }
        for (std::size_t i = 0; i < items.size(); ++i) {
            const bool shippable = fits[i] && !dead_groups.count(items[i]->group);
            (shippable ? items_ : unshippable_).push_back(items[i]);
        }
        sortCanonical(items_, full_);
        for (const FleetType& t : types_) {
            // Without prices, "cheapest" means "fewest containers".
            has_costs_ = has_costs_ || t.bin->cost > 0;
            weight_limited_ = weight_limited_ || t.bin->max_weight > 0;
        }
    }

    FleetPlan run() {
        std::vector<Solution> candidates;
        const std::vector<int> none(types_.size(), 0);
        // Fast constructions (what optimize=false uses) ...
        candidates.push_back(construct(Rule::Lookahead, -1, items_, none, true));
        candidates.push_back(construct(Rule::Ratio, -1, items_, none, true));
        if (full_.optimize) {
            // ... and, when optimising, more rules with every container planned in full.
            candidates.push_back(construct(Rule::Lookahead, -1, items_, none));
            candidates.push_back(construct(Rule::Ratio, -1, items_, none));
            candidates.push_back(construct(Rule::Largest, -1, items_, none));
            for (std::size_t t = 0; t < types_.size(); ++t) {
                if (types_[t].available != 0) candidates.push_back(construct(Rule::Only, static_cast<int>(t), items_, none));
            }
        }
        // Improve the most promising constructions first; one that is far more
        // expensive than the best improved fleet (and carries no more) is skipped.
        std::stable_sort(candidates.begin(), candidates.end(),
                         [&](const Solution& a, const Solution& b) { return better(a, b); });
        Solution best;
        bool have_best = false;
        for (Solution& s : candidates) {
            if (have_best && !profit() && !loadsMore(s, best) && totalCost(s) > 1.3 * totalCost(best) + 1e-9) continue;
            improve(s, false);
            if (!have_best || better(s, best)) {
                best = std::move(s);
                have_best = true;
            }
        }
        if (full_.optimize) improve(best, true);  // deep search on the winner only
        FleetPlan plan;
        plan.containers = std::move(best.containers);
        // Leftovers in input order, including what fits no container type.
        std::set<const Item*> left(best.rest.begin(), best.rest.end());
        left.insert(unshippable_.begin(), unshippable_.end());
        return finish(std::move(plan), left);
    }

    void setInputOrder(const std::vector<Item*>& items) { input_order_ = items; }

private:
    enum class Rule { Ratio, Largest, Only, Lookahead };

    bool profit() const { return full_.objective == Objective::Profit; }
    double unitCost(int t) const {
        if (full_.fleet_goal == FleetGoal::Count && !profit()) return 1.0;
        return has_costs_ ? types_[t].bin->cost : 1.0;
    }
    double binVolume(int t) const { return static_cast<double>(types_[t].bin->getVolume()); }
    bool available(int t, const std::vector<int>& used) const {
        return types_[t].available < 0 || used[t] < types_[t].available;
    }
    std::vector<int> usage(const Solution& s) const {
        std::vector<int> used(types_.size(), 0);
        for (const FleetContainer& c : s.containers) ++used[c.type];
        return used;
    }

    const BinPlan& evalQuick(int t, const std::vector<Item*>& items) {
        auto key = std::make_pair(t, items);
        auto it = cache_.find(key);
        if (it == cache_.end()) {
            it = cache_.emplace(std::move(key), planBin(*types_[t].bin, {}, items, quick_, true)).first;
        }
        return it->second;
    }
    BinPlan evalFull(int t, const FixedItems& fixed, const std::vector<Item*>& items) {
        if (!fixed.empty()) return planBin(*types_[t].bin, fixed, items, full_, true);
        auto key = std::make_pair(t, items);
        auto it = full_cache_.find(key);
        if (it == full_cache_.end()) {
            it = full_cache_.emplace(std::move(key), planBin(*types_[t].bin, {}, items, full_, true)).first;
        }
        return it->second;
    }
    // Feasibility checks of the improvement moves use the single fastest
    // strategy (if it fits everything, the full portfolio would too).
    BinPlan evalCheck(int t, const FixedItems& fixed, const std::vector<Item*>& items) {
        return planBin(*types_[t].bin, fixed, items, quick_, true);
    }

    static double volumeOf(const std::vector<Item*>& items) {
        double v = 0;
        for (const Item* item : items) v += static_cast<double>(item->getVolume());
        return v;
    }
    static double weightOf(const std::vector<Item*>& items) {
        double w = 0;
        for (const Item* item : items) w += item->weight;
        return w;
    }
    double weightCapacity(int t) const {
        return types_[t].bin->max_weight > 0 ? types_[t].bin->max_weight : std::numeric_limits<double>::infinity();
    }
    // Could this cargo possibly go into one container of type t (volume, weight)?
    bool mayFit(int t, double volume, double weight) const {
        return volume <= binVolume(t) * (1 + 1e-9) && weight <= weightCapacity(t) + 1e-6;
    }

    // Lower bound on the cost of carrying the cargo with the containers still
    // available: cheapest fractional cover of its volume, and of its weight.
    double coverLowerBound(double volume, double weight, const std::vector<int>& used) const {
        auto cover = [&](double need, auto capacity) {
            std::vector<std::pair<double, int>> rates;
            for (std::size_t t = 0; t < types_.size(); ++t) {
                const double cap = capacity(static_cast<int>(t));
                if (cap <= 0 || (types_[t].available >= 0 && used[t] >= types_[t].available)) continue;
                if (std::isinf(cap)) return 0.0;  // unlimited in this resource
                rates.push_back({unitCost(static_cast<int>(t)) / cap, static_cast<int>(t)});
            }
            std::sort(rates.begin(), rates.end());
            double cost = 0;
            for (const auto& [rate, t] : rates) {
                if (need <= 0) break;
                const double cap = capacity(t);
                const double count = types_[t].available < 0 ? std::numeric_limits<double>::infinity()
                                                             : static_cast<double>(types_[t].available - used[t]);
                const double take = std::min(need, cap * count);
                cost += take * rate;
                need -= take;
            }
            return need > 1e-9 ? std::numeric_limits<double>::infinity() : cost;
        };
        return std::max(cover(volume, [&](int t) { return binVolume(t); }),
                        cover(weight, [&](int t) { return weightCapacity(t); }));
    }

    // Share of the remaining work a load does: the scarcer of volume and weight.
    double workShare(const Score& s, const std::vector<Item*>& remaining) const {
        double volume = 0, weight = 0;
        for (const Item* item : remaining) {
            volume += static_cast<double>(item->getVolume());
            weight += item->weight;
        }
        double share = volume > 0 ? s.volume / volume : 0.0;
        if (weight_limited_ && weight > 0) share = std::max(share, s.weight / weight);
        if (full_.objective == Objective::Count && !remaining.empty()) {
            share = std::max(share, static_cast<double>(s.count) / remaining.size());
        }
        return share;
    }

    // Opens containers one at a time for `remaining` (see the file comment).
    // `commit_quick`: keep the fast single-strategy plan of each chosen
    // container instead of re-planning it with the full portfolio.
    Solution construct(Rule rule, int only, std::vector<Item*> remaining, std::vector<int> used,
                       bool commit_quick = false) {
        Solution sol;
        while (!remaining.empty()) {
            int chosen = -1, finisher = -1;
            double best_key = 0, best_tie = 0, best_work = 0;
            double min_rate = std::numeric_limits<double>::infinity();  // cheapest cost per unit of work
            for (std::size_t ti = 0; ti < types_.size(); ++ti) {
                const int t = static_cast<int>(ti);
                if (!available(t, used)) continue;
                const BinPlan& q = evalQuick(t, remaining);
                if (q.placed.empty()) continue;
                double key, tie;  // lower is better
                if (profit()) {
                    const double cost = types_[t].bin->cost;
                    const double gain = q.score.value - cost;
                    if (gain <= 0) continue;
                    key = rule == Rule::Ratio ? -(cost > 0 ? q.score.value / cost : std::numeric_limits<double>::infinity())
                                              : -gain;
                    tie = binVolume(t);
                } else {
                    if (q.rest.empty() && (finisher < 0 || unitCost(t) < unitCost(finisher) ||
                                           (close(unitCost(t), unitCost(finisher)) && binVolume(t) < binVolume(finisher)))) {
                        finisher = t;  // cheapest container taking everything that is left
                    }
                    const double work = std::max(workShare(q.score, remaining), 1e-12);
                    min_rate = std::min(min_rate, unitCost(t) / work);
                    key = rule == Rule::Largest ? -work : unitCost(t) / work;
                    tie = rule == Rule::Largest ? unitCost(t) : -work;
                    if (rule == Rule::Lookahead) {
                        // This container plus a lower bound on carrying what it leaves.
                        std::vector<int> after = used;
                        ++after[t];
                        key = unitCost(t) + coverLowerBound(volumeOf(q.rest), weightOf(q.rest), after);
                        tie = binVolume(t);
                    }
                }
                if (rule == Rule::Only && t == only) key = -std::numeric_limits<double>::infinity();
                if (chosen < 0 || key < best_key - 1e-12 || (close(key, best_key) && tie < best_tie)) {
                    chosen = t;
                    best_key = key;
                    best_tie = tie;
                    best_work = std::min(1.0, workShare(q.score, remaining));
                }
            }
            if (chosen < 0) break;
            // Finish now if that is no dearer than the chosen container plus the
            // rest of the work at the best rate any type achieves.
            const double estimate = unitCost(chosen) + (1.0 - best_work) * min_rate;
            if (rule != Rule::Lookahead && finisher >= 0 && chosen != finisher &&
                unitCost(finisher) <= estimate * (1 + 1e-9)) {
                chosen = finisher;
            }
            BinPlan plan = commit_quick ? evalQuick(chosen, remaining) : evalFull(chosen, {}, remaining);
            if (plan.placed.empty()) break;
            if (profit() && plan.score.value <= types_[chosen].bin->cost) break;
            remaining = plan.rest;
            sol.containers.push_back({chosen, std::move(plan)});
            ++used[chosen];
        }
        sol.rest = remaining;
        return sol;
    }

    // ---- comparison ------------------------------------------------------

    struct Metrics {
        std::map<int, double, std::greater<int>> loaded;  // objective per priority
        double cost = 0, volume = 0;
        int count = 0;
    };
    Metrics metrics(const Solution& s) const {
        Metrics m;
        for (const FleetContainer& c : s.containers) {
            for (const auto& [p, v] : c.plan.score.by_priority) m.loaded[p] += v;
            m.cost += types_[c.type].bin->cost;
            m.volume += binVolume(c.type);
            ++m.count;
        }
        if (profit()) {
            // Container cost is paid out of the lowest priority's value:
            // higher priorities still ship first, the rest must be profitable.
            const int lowest = m.loaded.empty() ? 0 : m.loaded.rbegin()->first;
            m.loaded[lowest] -= m.cost;
        }
        return m;
    }
    bool better(const Solution& a, const Solution& b) const {
        const Metrics x = metrics(a), y = metrics(b);
        std::set<int, std::greater<int>> levels;
        for (const auto& [p, v] : x.loaded) levels.insert(p);
        for (const auto& [p, v] : y.loaded) levels.insert(p);
        for (int p : levels) {
            const double u = x.loaded.count(p) ? x.loaded.at(p) : 0.0;
            const double v = y.loaded.count(p) ? y.loaded.at(p) : 0.0;
            if (!close(u, v)) return u > v;
        }
        const bool by_count = full_.fleet_goal == FleetGoal::Count || !has_costs_;
        const std::pair<double, double> kx = by_count ? std::make_pair(double(x.count), x.cost)
                                                      : std::make_pair(x.cost, double(x.count));
        const std::pair<double, double> ky = by_count ? std::make_pair(double(y.count), y.cost)
                                                      : std::make_pair(y.cost, double(y.count));
        if (!close(kx.first, ky.first)) return kx.first < ky.first;
        if (!close(kx.second, ky.second)) return kx.second < ky.second;
        return !close(x.volume, y.volume) && x.volume < y.volume;
    }

    double totalCost(const Solution& s) const {
        double cost = 0;
        for (const FleetContainer& c : s.containers) cost += unitCost(c.type);
        return cost;
    }
    bool loadsMore(const Solution& a, const Solution& b) const {
        Metrics x = metrics(a), y = metrics(b);
        std::set<int, std::greater<int>> levels;
        for (const auto& [p, v] : x.loaded) levels.insert(p);
        for (const auto& [p, v] : y.loaded) levels.insert(p);
        for (int p : levels) {
            const double u = x.loaded.count(p) ? x.loaded.at(p) : 0.0;
            const double v = y.loaded.count(p) ? y.loaded.at(p) : 0.0;
            if (!close(u, v)) return u > v;
        }
        return false;
    }

    // ---- improvement -----------------------------------------------------

    double fill(const FleetContainer& c) const { return c.plan.score.volume / binVolume(c.type); }

    // Empties one container into the others.
    bool eliminate(Solution& s) {
        std::vector<std::size_t> order(s.containers.size());
        std::iota(order.begin(), order.end(), 0);
        std::sort(order.begin(), order.end(), [&](std::size_t a, std::size_t b) {
            return fill(s.containers[a]) < fill(s.containers[b]);
        });
        double free_volume = 0, free_weight = 0;
        for (const FleetContainer& c : s.containers) {
            free_volume += binVolume(c.type) - c.plan.score.volume;
            free_weight += weightCapacity(c.type) - c.plan.score.weight;
        }
        for (std::size_t i : order) {
            std::vector<Item*> moving = itemsOf(s.containers[i].plan);
            const FleetContainer& from = s.containers[i];
            // The others' spare room must at least hold the load.
            if (from.plan.score.volume > free_volume - (binVolume(from.type) - from.plan.score.volume) + 1e-6 ||
                from.plan.score.weight > free_weight - (weightCapacity(from.type) - from.plan.score.weight) + 1e-6) {
                continue;
            }
            sortCanonical(moving, full_);
            std::vector<std::size_t> targets;
            for (std::size_t j = 0; j < s.containers.size(); ++j) {
                if (j != i) targets.push_back(j);
            }
            std::sort(targets.begin(), targets.end(), [&](std::size_t a, std::size_t b) {
                return binVolume(s.containers[a].type) - s.containers[a].plan.score.volume >
                       binVolume(s.containers[b].type) - s.containers[b].plan.score.volume;
            });
            targets.resize(std::min<std::size_t>(targets.size(), 12));  // the most spare room
            std::map<std::size_t, BinPlan> updated;
            for (std::size_t j : targets) {
                if (moving.empty()) break;
                const FleetContainer& target = s.containers[j];
                if (binVolume(target.type) - target.plan.score.volume <= 0) continue;
                BinPlan plan = evalCheck(target.type, target.plan.placed, moving);
                if (plan.rest.size() == moving.size()) continue;
                moving = plan.rest;
                plan.score = rescore(plan);
                updated[j] = std::move(plan);
            }
            if (!moving.empty()) continue;
            Solution next = s;
            for (auto& [j, plan] : updated) next.containers[j].plan = std::move(plan);
            next.containers.erase(next.containers.begin() + static_cast<std::ptrdiff_t>(i));
            if (better(next, s)) {
                s = std::move(next);
                return true;
            }
        }
        return false;
    }

    // Replaces two containers by one holding both loads.
    bool merge(Solution& s) {
        std::vector<std::size_t> order(s.containers.size());
        std::iota(order.begin(), order.end(), 0);
        std::sort(order.begin(), order.end(), [&](std::size_t a, std::size_t b) {
            return fill(s.containers[a]) < fill(s.containers[b]);
        });
        order.resize(std::min<std::size_t>(order.size(), 6));  // the lightest loads
        std::vector<int> used = usage(s);
        for (std::size_t a = 0; a < order.size(); ++a) {
            for (std::size_t b = a + 1; b < order.size(); ++b) {
                const std::size_t i = order[a], j = order[b];
                const int ti = s.containers[i].type, tj = s.containers[j].type;
                std::vector<Item*> both = itemsOf(s.containers[i].plan);
                const std::vector<Item*> more = itemsOf(s.containers[j].plan);
                both.insert(both.end(), more.begin(), more.end());
                sortCanonical(both, full_);
                --used[ti];
                --used[tj];
                const double volume = volumeOf(both), weight = weightOf(both);
                for (int u : typesByCost()) {
                    if (!available(u, used) || !mayFit(u, volume, weight)) continue;
                    if (unitCost(u) >= unitCost(ti) + unitCost(tj) - 1e-9 && !(full_.fleet_goal == FleetGoal::Count)) continue;
                    BinPlan plan = evalCheck(u, {}, both);
                    if (!plan.rest.empty()) continue;
                    Solution next = s;
                    next.containers[i] = {u, std::move(plan)};
                    next.containers.erase(next.containers.begin() + static_cast<std::ptrdiff_t>(j));
                    if (better(next, s)) {
                        s = std::move(next);
                        return true;
                    }
                }
                ++used[ti];
                ++used[tj];
            }
        }
        return false;
    }

    // Moves a load into a cheaper (or, at equal cost, smaller) container type.
    bool downsize(Solution& s) {
        std::vector<int> used = usage(s);
        for (std::size_t i = 0; i < s.containers.size(); ++i) {
            const int t = s.containers[i].type;
            std::vector<Item*> load = itemsOf(s.containers[i].plan);
            sortCanonical(load, full_);
            for (int u : typesByCost()) {
                if (u == t || !available(u, used)) continue;
                const bool cheaper = unitCost(u) < unitCost(t) - 1e-9 ||
                                     (close(unitCost(u), unitCost(t)) && binVolume(u) < binVolume(t));
                if (!cheaper) continue;
                if (!mayFit(u, s.containers[i].plan.score.volume, s.containers[i].plan.score.weight)) continue;
                BinPlan plan = evalCheck(u, {}, load);
                if (!plan.rest.empty()) continue;
                Solution next = s;
                next.containers[i] = {u, std::move(plan)};
                if (better(next, s)) {
                    s = std::move(next);
                    return true;
                }
            }
        }
        return false;
    }

    // Unshipped cargo: into spare space first, then into extra containers.
    bool fillUp(Solution& s) {
        if (s.rest.empty()) return false;
        Solution next = s;
        for (FleetContainer& c : next.containers) {
            if (next.rest.empty()) break;
            if (binVolume(c.type) - c.plan.score.volume <= 0) continue;
            BinPlan plan = evalCheck(c.type, c.plan.placed, next.rest);
            if (plan.rest.size() == next.rest.size()) continue;
            next.rest = plan.rest;
            plan.score = rescore(plan);
            c.plan = std::move(plan);
        }
        if (!next.rest.empty()) {
            // Open more containers for what is still left, as in construction.
            std::vector<Item*> left = next.rest;
            sortCanonical(left, full_);
            Solution more = construct(Rule::Ratio, -1, left, usage(next));
            for (FleetContainer& c : more.containers) next.containers.push_back(std::move(c));
            next.rest = std::move(more.rest);
        }
        if (better(next, s)) {
            s = std::move(next);
            return true;
        }
        return false;
    }

    // Profit: a container whose cargo is worth less than the container is not booked.
    bool dropUnprofitable(Solution& s) {
        if (!profit()) return false;
        for (std::size_t i = 0; i < s.containers.size(); ++i) {
            if (s.containers[i].plan.score.value >= types_[s.containers[i].type].bin->cost) continue;
            Solution next = s;
            const std::vector<Item*> load = itemsOf(next.containers[i].plan);
            next.rest.insert(next.rest.end(), load.begin(), load.end());
            next.containers.erase(next.containers.begin() + static_cast<std::ptrdiff_t>(i));
            if (better(next, s)) {
                s = std::move(next);
                return true;
            }
        }
        return false;
    }

    // Destroy and rebuild: re-plans the cargo of a few containers (each one
    // alone, and pairs / triples of the lightest loads) from scratch with
    // every construction rule; e.g. splits one big container into two cheaper
    // ones, or turns three small ones into one medium.
    bool rebuild(Solution& s) {
        std::vector<std::size_t> order(s.containers.size());
        std::iota(order.begin(), order.end(), 0);
        std::sort(order.begin(), order.end(), [&](std::size_t a, std::size_t b) {
            return fill(s.containers[a]) < fill(s.containers[b]);
        });
        // Each of the 5 lightest loads alone, and pairs / triples of the 4 lightest.
        std::vector<std::vector<std::size_t>> subsets;
        for (std::size_t k = 0; k < std::min<std::size_t>(order.size(), 5); ++k) subsets.push_back({order[k]});
        const std::size_t light = std::min<std::size_t>(order.size(), 4);
        for (std::size_t a = 0; a < light; ++a) {
            for (std::size_t b = a + 1; b < light; ++b) {
                subsets.push_back({order[a], order[b]});
                for (std::size_t c = b + 1; c < light; ++c) subsets.push_back({order[a], order[b], order[c]});
            }
        }
        for (const auto& subset : subsets) {
            Solution kept;
            std::vector<Item*> cargo;
            for (std::size_t i = 0; i < s.containers.size(); ++i) {
                if (std::find(subset.begin(), subset.end(), i) != subset.end()) {
                    const std::vector<Item*> load = itemsOf(s.containers[i].plan);
                    cargo.insert(cargo.end(), load.begin(), load.end());
                } else {
                    kept.containers.push_back(s.containers[i]);
                }
            }
            sortCanonical(cargo, full_);
            const std::vector<int> used = usage(kept);
            // The same cargo with the same containers left cannot succeed later.
            std::vector<Item*> key_items = cargo;
            std::sort(key_items.begin(), key_items.end());
            auto memo_key = std::make_pair(std::move(key_items), used);
            if (failed_rebuilds_.count(memo_key)) continue;
            if (!profit()) {
                double subset_cost = 0;
                for (std::size_t i : subset) subset_cost += unitCost(s.containers[i].type);
                // Even a perfect re-plan could not be cheaper: skip.
                if (coverLowerBound(volumeOf(cargo), weightOf(cargo), used) >= subset_cost - 1e-9) continue;
            }
            std::vector<std::pair<Rule, int>> rules = {{Rule::Lookahead, -1}, {Rule::Ratio, -1}, {Rule::Largest, -1}};
            for (std::size_t t = 0; t < types_.size(); ++t) rules.push_back({Rule::Only, static_cast<int>(t)});
            for (const auto& [rule, only] : rules) {
                Solution part = construct(rule, only, cargo, used);
                if (!part.rest.empty()) continue;  // must still carry all of it
                Solution next = kept;
                next.rest = s.rest;
                for (FleetContainer& c : part.containers) next.containers.push_back(std::move(c));
                if (better(next, s)) {
                    s = std::move(next);
                    return true;
                }
            }
            failed_rebuilds_.insert(std::move(memo_key));
        }
        return false;
    }

    // Local search; the expensive destroy-and-rebuild move only when asked.
    void improve(Solution& s, bool deep) {
        for (int round = 0; round < 50; ++round) {
            const bool changed = dropUnprofitable(s) || eliminate(s) || (full_.optimize && merge(s)) ||
                                 downsize(s) || fillUp(s) || (deep && rebuild(s));
            if (!changed) break;
        }
    }

    // Score of all items of a plan (plans with fixed items only score the new ones).
    Score rescore(const BinPlan& plan) const {
        Score score;
        for (const auto& [item, p] : plan.placed) score.add(*item, full_.objective);
        return score;
    }

    std::vector<int> typesByCost() const {
        std::vector<int> order(types_.size());
        std::iota(order.begin(), order.end(), 0);
        std::stable_sort(order.begin(), order.end(), [&](int a, int b) {
            if (!close(unitCost(a), unitCost(b))) return unitCost(a) < unitCost(b);
            return binVolume(a) < binVolume(b);
        });
        return order;
    }

    FleetPlan finish(FleetPlan plan, const std::set<const Item*>& left) const {
        for (Item* item : input_order_) {
            if (left.count(item)) plan.rest.push_back(item);
        }
        // Cheapest / smallest containers first, like single bins.
        std::stable_sort(plan.containers.begin(), plan.containers.end(),
                         [&](const FleetContainer& a, const FleetContainer& b) { return a.type < b.type; });
        return plan;
    }

    const std::vector<FleetType>& types_;
    PackingConfig full_, quick_;
    std::vector<Item*> items_, unshippable_, input_order_;
    bool has_costs_ = false, weight_limited_ = false;
    std::map<std::pair<int, std::vector<Item*>>, BinPlan> cache_, full_cache_;
    std::set<std::pair<std::vector<Item*>, std::vector<int>>> failed_rebuilds_;
};

}  // namespace

FleetPlan planFleet(const std::vector<Item*>& items, const std::vector<FleetType>& types,
                    const PackingConfig& config) {
    FleetPlanner planner(items, types, config);
    planner.setInputOrder(items);
    return planner.run();
}

}  // namespace binpack
