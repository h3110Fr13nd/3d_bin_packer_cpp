// loading_sequence.h - physically feasible loading order of a packed bin.
//
// A loading sequence is feasible for a given access side when every item, at
// its turn:
//   1. rests only on items that are already loaded (support), and
//   2. can be moved in a straight line from the access side to its spot
//      without passing through an item that is already loaded (access).
//
// Both rules are precedence constraints ("A before B"), so a feasible
// sequence exists exactly when the precedence graph has no cycle. Cycles are
// rare but possible (interlocking stacks with overhangs); the planner breaks
// them by taking out the most recently placed item of the cycle.
#pragma once

#include <array>
#include <cstddef>
#include <string>
#include <vector>

#include "packing_config.h"
#include "packing_engine.h"

namespace binpack {

struct SequenceBox {
    std::array<coord_t, 3> lo;  // back-bottom-left corner
    std::array<coord_t, 3> hi;  // front-top-right corner
    bool fixed = false;         // may not be removed to break a cycle (e.g. pre-placed)
};

struct SequencePlan {
    std::vector<std::size_t> order;    // indices of loaded boxes, in loading order
    std::vector<std::size_t> removed;  // boxes taken out to break cycles (and what lost support)
    bool feasible = true;              // false only if a cycle consists of fixed boxes
};

// Plans a feasible loading order. Boxes are expected in placement order (the
// later a box was placed, the sooner it is removed to break a cycle). Among
// the boxes that may go next, the one deepest in the bin along the access
// direction is taken (then the lowest, then back/left), e.g. nose-to-door and
// bottom-up for door access.
SequencePlan planLoadingSequence(const std::vector<SequenceBox>& boxes, LoadingAccess access,
                                 FillOrder fill_order, double min_support_ratio);

struct SequenceViolation {
    enum class Kind { NotSupported, PathBlocked };
    std::size_t step;   // position in the sequence of the offending box
    std::size_t other;  // position of the supporting box loaded later / the blocking box loaded earlier
    Kind kind;
    std::string describe() const;
};

// Checks a given order (boxes listed in loading order) against both rules.
std::vector<SequenceViolation> checkLoadingSequence(const std::vector<SequenceBox>& boxes_in_order,
                                                    LoadingAccess access);

}  // namespace binpack
