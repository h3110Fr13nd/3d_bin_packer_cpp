"""Bulk loads: one shaped product, one size, in full containers.

Spheres, pyramids, cones and cylinders shipped in bulk go loose into the
container (held in place by clips of negligible size), one product per
container. Instead of one carton per piece, the pieces are placed in the
densest standard pattern for the shape:

* sphere: close packing. Hexagonal layers with the next layer in the
  hollows (HCP), or square layers each offset by half a ball (FCC); both
  fill 74 % of space against 52 % for a plain grid, which is also tried.
* cylinder: circles in a hexagonal (or square) pattern across the section,
  in slabs along the axis; the axis upright or lying along either direction.
* cone: tip-up and tip-down cones alternating in each row, one radius apart
  (their radii add up to the base radius at every height), rows sqrt(3)
  radii apart: about twice as many per layer as one cone per carton.
* pyramid: tip-up and tip-down pyramids alternating along each row, half a
  base apart (their sloping faces touch): about twice the carton count.

For each container type every allowed orientation and pattern is counted and
the best kept. Weight limits cap the count. ``upright=True`` keeps the shape's
height vertical and the tip up (no tip-down cones or pyramids).

``pack_bulk`` chooses the containers: full containers of the best type, the
remainder in the cheapest container that holds it, the rest of that container
left empty. The result renders with every ``binpack.render`` function.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field

import numpy as np

import pybinding as _core

from . import _shapes

_EPS = 1e-9
_SQRT3_2 = math.sqrt(3) / 2


# ----------------------------------------------------------------- patterns --
# Patterns are built in "unit" coordinates: every axis scaled so the piece's
# box is 1 x 1 x 1 (an axis-aligned scaling keeps shapes disjoint, so a circle
# pattern also packs ellipses). A piece at p occupies [p, p + 1] on each axis.

def _fit(length: float, start: float, pitch: float) -> np.ndarray:
    """Positions start, start + pitch, ... that leave room for a unit piece."""
    if length - 1 - start < -_EPS:
        return np.zeros(0)
    return start + pitch * np.arange(int(math.floor((length - 1 - start) / pitch + _EPS)) + 1)


def _rows(lp, lq, pitch, row_gap, row_start, q0=0.0, flip=None):
    """A 2D pattern of rows along p: (p, q, inverted) arrays.

    Row k lies at q = q0 + k * row_gap and starts at row_start(k) mod pitch.
    flip(j, k) says which pieces stand on their tip."""
    ps, qs, fs = [], [], []
    for k, q in enumerate(_fit(lq, q0, row_gap)):
        p = _fit(lp, row_start(k) % pitch, pitch)
        ps.append(p)
        qs.append(np.full(len(p), q))
        j = np.arange(len(p))
        fs.append(flip(j, k) if flip else np.zeros(len(p), dtype=bool))
    if not ps:
        return np.zeros(0), np.zeros(0), np.zeros(0, dtype=bool)
    return np.concatenate(ps), np.concatenate(qs), np.concatenate(fs)


def _square(lp, lq):
    return _rows(lp, lq, 1.0, 1.0, lambda k: 0.0)


def _hexagonal(lp, lq):
    """Circles in offset rows (each circle touches six)."""
    return _rows(lp, lq, 1.0, _SQRT3_2, lambda k: 0.5 * k)


def _cones_interlocked(lp, lq):
    """Tip-up / tip-down cones alternating half a diameter apart; rows sqrt(3)/2 apart
    with the orientations swapped, so equal cones stay a diameter apart."""
    return _rows(lp, lq, 0.5, _SQRT3_2, lambda k: 0.0, flip=lambda j, k: (j + k) % 2 == 1)


def _pyramids_alternating(lp, lq):
    """Tip-up / tip-down pyramids alternating half a base apart along each row."""
    return _rows(lp, lq, 0.5, 1.0, lambda k: 0.0, flip=lambda j, k: j % 2 == 1)


def _layers(length, layer_a, layer_b, gap):
    """Stack 2D layers along the third axis, alternating layer_a / layer_b."""
    out = []
    for k, s in enumerate(_fit(length, 0.0, gap)):
        p, q, f = layer_a if k % 2 == 0 else layer_b
        out.append((p, q, np.full(len(p), s), f))
    return out


def _assemble(parts, axes):
    """(p, q, s, inverted) parts -> (n, 3) unit positions on placed axes (p_axis, q_axis, s_axis)."""
    parts = [x for x in parts if len(x[0])]
    if not parts:
        return np.zeros((0, 3)), np.zeros(0, dtype=bool)
    pos = np.zeros((sum(len(x[0]) for x in parts), 3))
    flips = np.concatenate([x[3] for x in parts])
    for column, axis in enumerate(axes):
        pos[:, axis] = np.concatenate([x[column] for x in parts])
    return pos, flips


def _sphere_patterns(L):
    """(name, unit positions, inverted) for balls in a container of unit size L."""
    out = []
    for s in (1, 0, 2):  # layers stacked along s (height first)
        p_axis, q_axis = [k for k in range(3) if k != s]
        for p, q in ((p_axis, q_axis), (q_axis, p_axis)):
            lp, lq = L[p], L[q]
            a = _hexagonal(lp, lq)
            b = _rows(lp, lq, 1.0, _SQRT3_2, lambda k: 0.5 + 0.5 * k, q0=_SQRT3_2 / 3)  # over the hollows
            out.append(("hexagonal close packing", _assemble(_layers(L[s], a, b, math.sqrt(2 / 3)), (p, q, s))))
        a = _square(L[p_axis], L[q_axis])
        b = _rows(L[p_axis], L[q_axis], 1.0, 1.0, lambda k: 0.5, q0=0.5)
        out.append(("square close packing (FCC)", _assemble(_layers(L[s], a, b, math.sqrt(0.5)),
                                                            (p_axis, q_axis, s))))
    a = _square(L[0], L[2])
    out.append(("grid", _assemble(_layers(L[1], a, a, 1.0), (0, 2, 1))))
    return out


def _axis_patterns(kind, L, axis, may_invert):
    """Patterns for cylinders, cones and pyramids with their height along `axis`:
    slabs one piece long along the axis, a 2D pattern across it."""
    p_axis, q_axis = [k for k in range(3) if k != axis]
    flat = {"grid": _square}
    if kind in (_core.Shape.CYLINDER, _core.Shape.CONE):
        flat["hexagonal"] = _hexagonal
    if may_invert and kind == _core.Shape.CONE:
        flat["alternating tip up / tip down"] = _cones_interlocked
    if may_invert and kind == _core.Shape.PYRAMID:
        flat["alternating tip up / tip down"] = _pyramids_alternating
    out = []
    for name, pattern in flat.items():
        for p, q in ((p_axis, q_axis), (q_axis, p_axis)):
            layer = pattern(L[p], L[q])
            out.append((name, _assemble(_layers(L[axis], layer, layer, 1.0), (p, q, axis))))
    return out


# ------------------------------------------------------------------ results --

@dataclass
class BulkLayout:
    """The best arrangement of one product in one container type."""

    count: int                  # pieces per full container
    pattern: str                # e.g. "hexagonal close packing"
    rotation: object            # RotationType of every piece
    positions: np.ndarray       # (count, 3) back-bottom-left corners of the pieces' boxes, loading order
    inverted: np.ndarray        # (count,) pieces standing on their tip
    carton_count: int           # what one carton per piece would hold (same container)
    limited_by_weight: bool = False


class BulkPiece:
    """One piece of a bulk load. Reads like a packed ``Item`` (``get_position``,
    ``get_dimension``, ...), so reports and pictures work unchanged. Positions
    may be fractions; ``inverted`` pieces stand on their tip."""

    carton = False  # loose in the container: no carton outline in pictures

    def __init__(self, product, name, rotation, position, inverted):
        self._product = product
        self.name = name
        self.shape = product.shape
        self.width, self.height, self.depth = product.width, product.height, product.depth
        self.weight, self.value, self.color = product.weight, product.value, product.color
        self.group, self.priority, self.unfit_reason = product.group, product.priority, ""
        self.upright = product.upright
        self.crate_required = getattr(product, "crate_required", False)
        self.rotation_type = rotation
        self.position = tuple(float(x) for x in position)
        self.inverted = bool(inverted)

    def get_name(self):
        return self.name

    def get_position(self):
        return self.position

    def get_rotation_type(self):
        return self.rotation_type

    def get_dimension(self):
        return list(_core_rotated(self.width, self.height, self.depth, self.rotation_type))

    def get_volume(self) -> float:
        """Volume of the piece itself (not of its box)."""
        return solid_volume(self._product)

    def __repr__(self):
        x, y, z = self.position
        tip = ", tip down" if self.inverted else ""
        return f"<BulkPiece {self.name} {self.shape.name.lower()} at ({x:.0f}, {y:.0f}, {z:.0f}){tip}>"


class BulkContainer:
    """A container of a bulk load. Reads like a packed ``Bin``."""

    def __init__(self, bin_, name, pieces, layout: BulkLayout, type_index: int):
        self.name = name
        self.width, self.height, self.depth = bin_.width, bin_.height, bin_.depth
        self.max_weight, self.cost = bin_.max_weight, bin_.cost
        self.type_index = type_index
        self.layout = layout
        self.items = pieces

    def get_name(self):
        return self.name

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height

    def get_depth(self):
        return self.depth

    def get_volume(self):
        return self.width * self.height * self.depth

    def get_items(self):
        return list(self.items)

    def get_total_weight(self):
        return sum(p.weight for p in self.items)

    def get_utilization(self):
        """Share of the container volume filled by the pieces themselves."""
        return sum(p.get_volume() for p in self.items) / max(1, self.get_volume())


@dataclass
class BulkPlan:
    """Containers for a bulk quantity of one product. Reads like a packed ``Packer``."""

    product: object
    quantity: int
    containers: list
    layouts: dict = field(default_factory=dict)   # container type name -> BulkLayout (None: doesn't fit)
    unfit: list = field(default_factory=list)

    def get_bins(self):
        return list(self.containers)

    def get_items(self):
        return [p for c in self.containers for p in c.items]

    def get_unfit_items(self):
        return list(self.unfit)

    def get_total_cost(self):
        return float(sum(c.cost for c in self.containers))

    def get_bin_types(self):
        return []


# ----------------------------------------------------------------- planning --

def _core_rotated(w, h, d, rotation):
    axes = _shapes._AXES[rotation]
    dims = (w, h, d)
    return tuple(dims[a] for a in axes)


def solid_volume(item) -> float:
    """Volume of the shape itself (a sphere fills pi/6 of its box, a cone pi/12, ...)."""
    box = float(item.width) * item.height * item.depth
    return box * {_core.Shape.SPHERE: math.pi / 6, _core.Shape.CYLINDER: math.pi / 4,
                  _core.Shape.CONE: math.pi / 12, _core.Shape.PYRAMID: 1 / 3}.get(item.shape, 1.0)


def _carton_count(item, bin_) -> int:
    size = (bin_.width, bin_.height, bin_.depth)
    best = 0
    for r in item.get_effective_rotations():
        dims = _core_rotated(item.width, item.height, item.depth, r)
        best = max(best, int(np.prod([s // d for s, d in zip(size, dims)])))
    return best


def bulk_layout(item, bin_, order: str = "door") -> BulkLayout | None:
    """The densest standard arrangement of `item` in `bin_` (None if not even one fits).

    Pieces come in loading order. ``order="door"``: from the back (nose) to
    the door, bottom to top, left to right. ``order="bottom"``: layer by
    layer from the floor (crates, filled from above).
    """
    if item.shape == _core.Shape.BOX:
        raise ValueError("bulk loading is for shaped goods (sphere, pyramid, cone, cylinder); use Packer for boxes")
    size = np.array([bin_.width, bin_.height, bin_.depth], dtype=float)
    best = None
    seen = set()
    for rotation in item.get_effective_rotations():
        dims = np.array(_core_rotated(item.width, item.height, item.depth, rotation), dtype=float)
        axis = _shapes._AXES[rotation].index(1)  # placed axis of the item's height
        key = (tuple(dims), axis if item.shape != _core.Shape.SPHERE else None)
        if key in seen or np.any(dims > size) or np.any(dims <= 0):
            continue
        seen.add(key)
        L = size / dims
        if item.shape == _core.Shape.SPHERE:
            patterns = _sphere_patterns(L)
        else:  # tip down only when that doesn't break "this side up"
            patterns = _axis_patterns(item.shape, L, axis, may_invert=not (axis == 1 and item.upright))
        for name, (unit, flips) in patterns:
            if best is None or len(unit) > len(best[1]):
                best = (name, unit, flips, rotation, dims)
    if best is None or len(best[1]) == 0:
        return None
    name, unit, flips, rotation, dims = best
    pos = unit * dims
    x, y, z = (pos[:, k].round(6) for k in range(3))
    order = np.lexsort((x, z, y) if order == "bottom" else (x, y, z))  # last key sorts first
    count, limited = len(pos), False
    if item.weight > 0 and bin_.max_weight > 0 and count * item.weight > bin_.max_weight:
        count, limited = int(math.floor(bin_.max_weight / item.weight + 1e-9)), True
        order = order[:count]
    return BulkLayout(count, name, rotation, pos[order], flips[order], _carton_count(item, bin_), limited)


def pack_bulk(item, quantity: int, bins) -> BulkPlan:
    """Containers for `quantity` pieces of one shaped product, loaded loose in
    the densest pattern (see :func:`bulk_layout`).

    bins: the container types that can be booked (each as often as needed),
    with ``cost``. The plan is the cheapest (then fewest, then smallest) of:
    all pieces in containers of one type, or full containers of one type plus
    the remainder in one container of any type. The last container is only
    filled as far as needed; the rest stays empty.
    """
    if quantity < 0:
        raise ValueError("quantity must be >= 0")
    bins = list(bins)
    if not bins:
        raise ValueError("no container types given")
    layouts = [bulk_layout(item, b) for b in bins]
    usable = [k for k, lay in enumerate(layouts) if lay is not None and lay.count > 0]
    by_name = {b.get_name(): lay for b, lay in zip(bins, layouts)}
    if not usable:
        unfit = [BulkPiece(item, f"{item.name} {i + 1}", item.get_effective_rotations()[0], (0, 0, 0), False)
                 for i in range(quantity)]
        for p in unfit:
            p.unfit_reason = "too large (or too heavy) for every container"
        return BulkPlan(item, quantity, [], by_name, unfit)

    def score(plan):  # [(type, pieces), ...]
        cost = sum(bins[k].cost for k, _ in plan)
        volume = sum(bins[k].get_volume() for k, _ in plan)
        return cost, len(plan), volume

    best = None
    for k in usable:
        full, rest = divmod(quantity, layouts[k].count)
        options = [[(k, layouts[k].count)] * full + ([(k, rest)] if rest else [])]
        if rest:
            options += [[(k, layouts[k].count)] * full + [(m, rest)] for m in usable if layouts[m].count >= rest]
        for plan in options:
            if best is None or score(plan) < score(best):
                best = plan

    containers, counter, seq = [], {}, 0
    for k, n in best:
        counter[k] = counter.get(k, 0) + 1
        lay = layouts[k]
        pieces = []
        for pos, flip in zip(lay.positions[:n], lay.inverted[:n]):
            seq += 1
            pieces.append(BulkPiece(item, f"{item.name} {seq}", lay.rotation, pos, flip))
        containers.append(BulkContainer(bins[k], f"{bins[k].get_name()} #{counter[k]}", pieces, lay, k))
    return BulkPlan(item, quantity, containers, by_name)


# ------------------------------------------------------------------ reports --

def bulk_rows(plan: BulkPlan) -> list[dict]:
    """One row per piece, container by container, in loading order (positions in the bin's units)."""
    rows = []
    for b_index, c in enumerate(plan.containers):
        for step, p in enumerate(c.items, 1):
            x, y, z = p.position
            dx, dy, dz = p.get_dimension()
            rows.append({"bin_index": b_index, "bin": c.name, "step": step, "item": p.name,
                         "shape": p.shape.name.lower(), "x": round(x, 1), "y": round(y, 1), "z": round(z, 1),
                         "length_x": dx, "height_y": dy, "depth_z": dz, "rotation": p.rotation_type.name,
                         "tip_down": p.inverted, "weight": p.weight})
    return rows


def bulk_to_csv(plan: BulkPlan, path: str) -> None:
    rows = bulk_rows(plan)
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["bin", "step", "item"])
        writer.writeheader()
        writer.writerows(rows)


def format_bulk(plan: BulkPlan) -> str:
    """Which containers, how each is filled, and the gain over one carton per piece."""
    p = plan.product
    head = (f"Bulk load: {plan.quantity} x {p.name} ({p.shape.name.lower()} {p.width}x{p.height}x{p.depth})"
            f" in {len(plan.containers)} container{'s' if len(plan.containers) != 1 else ''}")
    if plan.get_total_cost():
        head += f", total cost {plan.get_total_cost():,.2f}"
    lines = [head]
    for name, lay in plan.layouts.items():
        if lay is None:
            lines.append(f"  {name}: does not fit")
            continue
        gain = f", {lay.count / lay.carton_count:.2f}x" if lay.carton_count else ""
        weight = " (weight limit)" if lay.limited_by_weight else ""
        lines.append(f"  {name}: {lay.count} per container{weight} - {lay.pattern}, rotation {lay.rotation.name}"
                     f" (one carton per piece: {lay.carton_count}{gain})")
    for c in plan.containers:
        full = "full" if len(c.items) == c.layout.count else f"{len(c.items)} of {c.layout.count}, rest empty"
        lines.append(f"== {c.name}: {len(c.items)} pieces ({full}), {c.get_utilization():.1%} of volume, "
                     f"{c.get_total_weight():,.1f} weight" + (f", cost {c.cost:,.2f}" if c.cost else "") + " ==")
        tips = int(sum(pc.inverted for pc in c.items))
        if tips:
            lines.append(f"   {tips} pieces tip down")
    if plan.unfit:
        lines.append(f"== Not loaded: {len(plan.unfit)} pieces: {plan.unfit[0].unfit_reason} ==")
    return "\n".join(lines)
