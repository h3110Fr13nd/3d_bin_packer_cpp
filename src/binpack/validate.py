"""Independent audit of a packing result.

``validate(packer)`` re-checks every rule with vectorised numpy code that
shares nothing with the C++ packer, so it can be used to double-check plans,
including plans edited by hand.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

import pybinding as _core

from . import _shapes
from ._geometry import boxes_array, interval_overlap, row_blocks

_UPRIGHT = {_core.RotationType.whd, _core.RotationType.dhw}


@dataclass(frozen=True)
class Issue:
    """One broken rule. ``step`` is the 1-based position in the bin's loading order."""

    bin: str
    step: int
    item: str
    check: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.bin}] step {self.step} '{self.item}': {self.check} - {self.detail}"


def _access_blocks(lo, hi, i0, i1, access):
    """Boolean (i1-i0, n) matrix: box j lies in the straight path of box i to the access side."""
    a, b = slice(i0, i1), None
    ox = interval_overlap(lo[a, 0, b], hi[a, 0, b], lo[None, :, 0], hi[None, :, 0]) > 0
    oy = interval_overlap(lo[a, 1, b], hi[a, 1, b], lo[None, :, 1], hi[None, :, 1]) > 0
    oz = interval_overlap(lo[a, 2, b], hi[a, 2, b], lo[None, :, 2], hi[None, :, 2]) > 0
    A = _core.LoadingAccess
    if access == A.DOOR:
        return (lo[None, :, 2] >= hi[a, 2, b]) & ox & oy
    if access == A.TOP:
        return (lo[None, :, 1] >= hi[a, 1, b]) & ox & oz
    if access == A.RIGHT_SIDE:
        return (lo[None, :, 0] >= hi[a, 0, b]) & oy & oz
    if access == A.LEFT_SIDE:
        return (hi[None, :, 0] <= lo[a, 0, b]) & oy & oz
    return np.zeros((i1 - i0, len(lo)), dtype=bool)


def validate_bin(bin_, min_support_ratio: float = 0.75, loading_access=None) -> list[Issue]:
    """Checks one bin. ``loading_access=None`` skips the loading-order check."""
    items = list(bin_.get_items())
    issues: list[Issue] = []
    name = bin_.get_name()

    def report(k, check, detail):
        issues.append(Issue(name, k + 1, items[k].name, check, detail))

    n = len(items)
    if n == 0:
        return issues
    lo, hi = boxes_array(items)
    size = np.array([bin_.get_width(), bin_.get_height(), bin_.get_depth()])
    weight = np.array([it.weight for it in items], dtype=float)
    volume_full = np.all(hi > lo, axis=1)  # zero-size items take no space

    for k in np.nonzero(np.any(lo < 0, axis=1) | np.any(hi > size, axis=1))[0]:
        report(k, "bounds", f"extends outside the bin ({tuple(lo[k])} .. {tuple(hi[k])})")

    for k, it in enumerate(items):
        if getattr(it, "crate_required", False) and getattr(it, "crate_index", -1) < 0:
            report(k, "crate", "must travel in a crate but is loaded loose")
        rot = it.get_rotation_type()
        if rot not in it.get_allowed_rotations():
            report(k, "rotation", f"{rot} is not an allowed rotation")
        if it.upright and rot not in _UPRIGHT:
            report(k, "upright", f"must keep its height vertical, placed as {rot}")
        if it.bottom_load_only and lo[k, 1] != 0:
            report(k, "floor only", f"placed at height {lo[k, 1]}")

    base = (hi[:, 0] - lo[:, 0]) * (hi[:, 2] - lo[:, 2])
    for i0, i1 in row_blocks(n):
        rows = slice(i0, i1)
        ox = interval_overlap(lo[rows, None, 0], hi[rows, None, 0], lo[None, :, 0], hi[None, :, 0])
        oy = interval_overlap(lo[rows, None, 1], hi[rows, None, 1], lo[None, :, 1], hi[None, :, 1])
        oz = interval_overlap(lo[rows, None, 2], hi[rows, None, 2], lo[None, :, 2], hi[None, :, 2])
        area = ox * oz

        collide = (ox > 0) & (oy > 0) & (oz > 0)
        idx = np.arange(i0, i1)[:, None]
        collide &= idx < np.arange(n)[None, :]  # each pair once
        for r, j in zip(*np.nonzero(collide)):
            report(i0 + r, "overlap", f"intersects '{items[j].name}' (step {j + 1})")

        # Support: share of the base resting on tops exactly at this height.
        touching = hi[None, :, 1] == lo[rows, None, 1]
        supported = np.where(touching, area, 0).sum(axis=1)
        for r in range(i1 - i0):
            k = i0 + r
            if lo[k, 1] > 0 and base[k] > 0 and supported[r] < min_support_ratio * base[k] - 1e-9:
                report(k, "support", f"only {supported[r] / base[k]:.0%} of its base is supported "
                                     f"(minimum {min_support_ratio:.0%})")

        # Stacking rules: everything above the item with footprint overlap.
        above = (lo[None, :, 1] >= hi[rows, None, 1]) & (area > 0)
        for r in range(i1 - i0):
            k = i0 + r
            it = items[k]
            js = np.nonzero(above[r])[0]
            if len(js) == 0:
                continue
            if it.is_disable_stacking() or it.is_height_constrained():
                report(k, "no stacking", f"{len(js)} item(s) above it, e.g. '{items[js[0]].name}'")
            if it.stuffing_height > 0 and np.any(hi[js, 1] > hi[k, 1] + it.stuffing_height):
                report(k, "stacking height", f"items above reach more than {it.stuffing_height} above it")
            if it.stuffing_layers > 0 and len(np.unique(lo[js, 1])) > it.stuffing_layers:
                report(k, "stacking layers", f"{len(np.unique(lo[js, 1]))} layers above it "
                                             f"(maximum {it.stuffing_layers})")
            if it.stuffing_max_weight > 0:
                load = float(np.sum(weight[js] * area[r, js] / np.maximum(base[js], 1)))
                if load > it.stuffing_max_weight + 1e-3:
                    report(k, "stacking weight", f"carries {load:.1f} (maximum {it.stuffing_max_weight})")

        if loading_access is not None and loading_access != _core.LoadingAccess.NONE:
            later = np.arange(n)[None, :] > idx
            earlier = ~later & (np.arange(n)[None, :] != idx)
            both = volume_full[rows, None] & volume_full[None, :]
            rests_on_later = touching & (area > 0) & later & both
            for r, j in zip(*np.nonzero(rests_on_later)):
                report(i0 + r, "loading order", f"rests on '{items[j].name}' (step {j + 1}), loaded later")
            blocked = _access_blocks(lo, hi, i0, i1, loading_access) & earlier & both
            for r, j in zip(*np.nonzero(blocked)):
                report(i0 + r, "loading order", f"path from the {loading_access.name.lower().replace('_', ' ')} "
                                                f"is blocked by '{items[j].name}' (step {j + 1}), loaded earlier")

    if bin_.max_weight > 0 and weight.sum() > bin_.max_weight + 1e-3:
        issues.append(Issue(name, 0, "-", "bin weight", f"{weight.sum():.1f} > limit {bin_.max_weight}"))
    return issues


def validate(packer, check_loading_order: bool = True) -> list[Issue]:
    """Audits every bin of a packed ``Packer`` plus the consignment groups.

    Returns a list of :class:`Issue` (empty = the plan is valid and loadable
    in the listed order from ``packer.loading_access``).
    """
    if hasattr(packer, "layouts") and hasattr(packer, "containers"):  # a bulk plan (binpack.bulk)
        return _validate_bulk(packer)
    access = packer.loading_access if check_loading_order else None
    issues: list[Issue] = []
    group_bins: dict[str, set[str]] = {}
    for b_index, bin_ in enumerate(packer.get_bins()):
        issues += validate_bin(bin_, packer.min_support_ratio, access)
        for it in bin_.get_items():
            if it.group:
                group_bins.setdefault(it.group, set()).add(f"{b_index}:{bin_.get_name()}")

    unfit_groups = {it.group for it in packer.get_unfit_items() if it.group}
    for group, bins in sorted(group_bins.items()):
        if len(bins) > 1:
            issues.append(Issue("-", 0, "-", "group", f"group '{group}' is split over bins {sorted(bins)}"))
        if group in unfit_groups:
            issues.append(Issue("-", 0, "-", "group", f"group '{group}' is only partly loaded"))

    issues += _validate_crates(packer)

    # Fleet: no more containers of a type than are available.
    types = packer.get_bin_types()
    used: dict[int, int] = {}
    for bin_ in packer.get_bins():
        if bin_.type_index >= 0 and bin_.get_items():
            used[bin_.type_index] = used.get(bin_.type_index, 0) + 1
    for t, n in sorted(used.items()):
        if t >= len(types):
            issues.append(Issue("-", 0, "-", "fleet", f"bin refers to unknown type {t}"))
        elif types[t].count is not None and n > types[t].count:
            issues.append(Issue("-", 0, "-", "fleet", f"{n} x '{types[t].bin.get_name()}' used, "
                                                      f"only {types[t].count} available"))

    packed = sum(len(b.get_items()) for b in packer.get_bins())
    unfit_n = len(packer.get_unfit_items()) - len(getattr(packer, "not_crated", ()))  # those never reached the loader
    if packed + unfit_n != len(packer.get_items()):
        issues.append(Issue("-", 0, "-", "count", f"{packed} packed + {unfit_n} unfit "
                                                  f"!= {len(packer.get_items())} items"))
    return issues


def _shaped_rules(pieces, where, report):
    """Loose shaped pieces (bulk loads, shaped crate contents): real shapes
    never overlap; allowed rotations; "this side up" goods stand on their base."""
    for i, j in _shapes.overlapping_pairs(pieces):
        report("overlap", f"shape intersects '{pieces[j].name}' (step {j + 1})", i + 1, pieces[i].name)
    for k, p in enumerate(pieces):
        product = getattr(p, "_product", None) or getattr(p, "_item", None) or p
        rotation = p.get_rotation_type()
        if rotation not in product.get_effective_rotations():
            report("rotation", f"{rotation} is not allowed {where}", k + 1, p.name)
        if product.upright and rotation not in _UPRIGHT:
            report("upright", f"must keep its height vertical, placed as {rotation}", k + 1, p.name)
        elif product.upright and getattr(p, "inverted", False):
            report("upright", "stands on its tip but must be kept this side up", k + 1, p.name)


def _validate_bulk(plan) -> list[Issue]:
    """Bulk plans: one product per container, pieces inside it and never
    overlapping, handling rules, weight limit, every piece accounted for."""
    issues: list[Issue] = []
    for c in plan.containers:
        def report(check, detail, step=0, item="-", name=c.name):
            issues.append(Issue(name, step, item, check, detail))

        pieces = list(c.items)
        if len({(p.shape, p.width, p.height, p.depth) for p in pieces}) > 1:
            report("product", "more than one product (shape and size) in the container")
        if pieces:
            lo, hi = boxes_array(pieces)
            size = np.array([c.get_width(), c.get_height(), c.get_depth()], dtype=float)
            for k in np.nonzero(np.any(lo < -1e-6, axis=1) | np.any(hi > size + 1e-6, axis=1))[0]:
                report("bounds", "extends outside the container", k + 1, pieces[k].name)
        _shaped_rules(pieces, "for the product", report)
        if c.max_weight > 0 and c.get_total_weight() > c.max_weight + 1e-3:
            report("bin weight", f"{c.get_total_weight():.1f} > limit {c.max_weight}")
    shipped = sum(len(c.items) for c in plan.containers) + len(plan.unfit)
    if shipped != plan.quantity:
        issues.append(Issue("-", 0, "-", "count", f"{shipped} pieces planned for a quantity of {plan.quantity}"))
    return issues


def _validate_crates(plan) -> list[Issue]:
    """Crate plans (binpack.crates): one kind of goods per crate, inside the
    inner space, within the weight limit; crates of boxes audited like a bin
    loaded from the top; no more crates of a type than are available."""
    crates = getattr(plan, "crates", None)
    if not crates:
        return []
    issues: list[Issue] = []
    used: dict[str, int] = {}
    for crate in crates:
        t = crate.type
        used[t.name] = used.get(t.name, 0) + 1
        goods = list(crate.contents)

        def report(check, detail, step=0, item="-"):
            issues.append(Issue(crate.name, step, item, check, detail))

        shapes = {it.shape for it in goods}
        if len(shapes) > 1:
            report("crate contents", f"mixes shapes {sorted(s.name.lower() for s in shapes)}")
        elif shapes and shapes != {_core.Shape.BOX} and len({(it.width, it.height, it.depth) for it in goods}) > 1:
            report("crate contents", "shaped goods of different sizes")
        if len({it.group for it in goods}) > 1:
            report("crate contents", "mixes consignments (groups)")
        if t.max_weight > 0 and crate.goods_weight > t.max_weight + 1e-3:
            report("crate weight", f"{crate.goods_weight:.1f} > limit {t.max_weight}")
        if shapes and shapes != {_core.Shape.BOX}:
            _shaped_rules(goods, "in the crate", lambda check, detail, step=0, item="-": report(check, detail, step, item))
        if goods:
            lo, hi = boxes_array(goods)
            outside = np.any(lo < -1e-6, axis=1) | np.any(hi > np.array(t.inner) + 1e-6, axis=1)
            for k in np.nonzero(outside)[0]:
                report("bounds", f"outside the inner space {t.inner}", k + 1, goods[k].name)
        if crate._bin is not None:  # boxes, packed like a small container loaded from above
            issues += [Issue(crate.name, i.step, i.item, i.check, i.detail)
                       for i in validate_bin(crate._bin, plan.min_support_ratio, _core.LoadingAccess.TOP)
                       if i.check not in ("bin weight", "crate")]  # weight checked above; they are in a crate
    # The crate as loaded: its size, weight and handling rules come from its type and its goods.
    for b in plan.get_bins():
        for it in b.get_items():
            if it.crate_index < 0:
                continue
            crate = crates[it.crate_index]
            t = crate.type

            def report(check, detail, name=crate.name):
                issues.append(Issue(name, 0, it.name, check, detail))

            if (it.width, it.height, it.depth) != tuple(t.outer):
                report("crate size", f"loaded as {it.width}x{it.height}x{it.depth}, the crate is {t.outer}")
            if abs(it.weight - crate.weight) > 1e-3 * max(1.0, crate.weight):
                report("crate weight", f"loaded as {it.weight:.1f}, tare + goods = {crate.weight:.1f}")
            needs_upright = t.upright or any(getattr(g, "upright", False) for g in crate.contents)
            if needs_upright and not it.upright:
                report("upright", "must be kept upright (its type or its goods)")
            if t.floor_only and not it.bottom_load_only:
                report("floor only", "must stand on the container floor")
            if not t.stackable and not it.disable_stacking:
                report("no stacking", "nothing may be loaded on top of it")
            if t.max_load > 0 and not (0 < it.stuffing_max_weight <= t.max_load + 1e-6):
                report("stacking weight", f"must carry at most {t.max_load}")

    # Every item accounted for: in a loaded crate, loaded loose, or not loaded.
    loaded = sum(len(crates[it.crate_index].contents) if it.crate_index >= 0 else 1
                 for b in plan.get_bins() for it in b.get_items())
    if loaded + len(plan.unloaded_goods()) != plan.total_goods:
        issues.append(Issue("-", 0, "-", "count", f"{loaded} loaded + {len(plan.unloaded_goods())} not loaded "
                                                  f"!= {plan.total_goods} items"))
    for t in getattr(plan, "crate_types", []):
        if t.count is not None and used.get(t.name, 0) > t.count:
            issues.append(Issue("-", 0, "-", "crates", f"{used[t.name]} x {t.name} used, {t.count} available"))
    return issues
