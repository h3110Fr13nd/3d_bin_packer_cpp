"""Loading plans and load summaries."""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from typing import Iterable

import numpy as np

from ._geometry import boxes_array, interval_overlap, row_blocks
from ._shapes import shape_name

PLAN_COLUMNS = ["bin_index", "bin", "bin_type", "bin_cost", "step", "item", "x", "y", "z", "length_x", "height_y",
                "depth_z", "rotation", "weight", "value", "priority", "group", "rests_on", "shape", "contents"]


def bin_type_name(packer, bin_) -> str:
    """Name of the container type a fleet bin was booked from ("" for bins added with add_bin)."""
    types = packer.get_bin_types()
    return types[bin_.type_index].bin.get_name() if 0 <= bin_.type_index < len(types) else ""


def _rests_on(items) -> list[list[int]]:
    """For every item, the 1-based steps of the items it stands on (vectorised)."""
    lo, hi = boxes_array(items)
    result: list[list[int]] = []
    for i0, i1 in row_blocks(len(items)):
        rows = slice(i0, i1)
        area = (interval_overlap(lo[rows, None, 0], hi[rows, None, 0], lo[None, :, 0], hi[None, :, 0]) *
                interval_overlap(lo[rows, None, 2], hi[rows, None, 2], lo[None, :, 2], hi[None, :, 2]))
        on = (hi[None, :, 1] == lo[rows, None, 1]) & (lo[rows, None, 1] > 0) & (area > 0)
        result += [(np.nonzero(r)[0] + 1).tolist() for r in on]
    return result


def loading_plan(packer) -> list[dict]:
    """One row per loaded item, bin by bin, in loading order.

    ``step`` is the 1-based loading step within the bin; ``rests_on`` lists
    the steps of the items it stands on (empty = on the floor). Positions are
    the item's back-bottom-left corner; sizes are as placed (rotation applied).
    ``shape`` is what the item really is ("box", "sphere", "cone", ...); it is
    loaded as its box (a thin carton) either way. For a crate plan
    (``pack_with_crates``), ``contents`` lists what a crate holds.
    """
    rows = []
    crates = getattr(packer, "crates", None)
    for b_index, bin_ in enumerate(packer.get_bins()):
        items = list(bin_.get_items())
        type_name = bin_type_name(packer, bin_)
        for step, (it, below) in enumerate(zip(items, _rests_on(items)), 1):
            crate = crates[it.crate_index] if crates is not None and it.crate_index >= 0 else None
            (x, y, z), (w, h, d) = it.get_position(), it.get_dimension()
            rows.append({
                "bin_index": b_index, "bin": bin_.get_name(), "bin_type": type_name, "bin_cost": bin_.cost,
                "step": step, "item": it.name,
                "x": x, "y": y, "z": z, "length_x": w, "height_y": h, "depth_z": d,
                "rotation": it.get_rotation_type().name, "weight": it.weight, "value": it.value,
                "priority": it.priority, "group": it.group, "rests_on": below, "shape": shape_name(it),
                "contents": crate.summary() if crate else "",
            })
    return rows


def plan_to_csv(packer, path: str) -> None:
    """Writes :func:`loading_plan` to a CSV file."""
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=PLAN_COLUMNS)
        writer.writeheader()
        for row in loading_plan(packer):
            writer.writerow({**row, "rests_on": " ".join(map(str, row["rests_on"]))})


def summary(packer) -> dict:
    """Totals per used bin, for the fleet, and for the overflow (items not loaded)."""
    bins = []
    by_type: dict[str, int] = {}
    for b_index, bin_ in enumerate(packer.get_bins()):
        items = list(bin_.get_items())
        if not items:
            continue
        type_name = bin_type_name(packer, bin_) or bin_.get_name()
        by_type[type_name] = by_type.get(type_name, 0) + 1
        bins.append({
            "bin_index": b_index, "bin": bin_.get_name(), "type": type_name, "cost": bin_.cost,
            "items": len(items),
            "volume_utilization": bin_.get_utilization(),
            "weight": bin_.get_total_weight(),
            "weight_utilization": (bin_.get_total_weight() / bin_.max_weight) if bin_.max_weight > 0 else None,
            "value": sum(it.value for it in items),
        })
    unfit = list(packer.get_unfit_items())
    total_cost = sum(b["cost"] for b in bins)
    loaded_value = sum(b["value"] for b in bins)
    return {
        "bins_used": len(bins),
        "bins": bins,
        "containers_by_type": by_type,
        "total_cost": total_cost,
        "profit": loaded_value - total_cost,
        "loaded_items": sum(b["items"] for b in bins),
        "loaded_value": loaded_value,
        "loaded_weight": sum(b["weight"] for b in bins),
        "unfit_items": len(unfit),
        "unfit_value": sum(it.value for it in unfit),
        "unfit_weight": sum(it.weight for it in unfit),
        "unfit_volume": sum(it.get_volume() for it in unfit),
        "unfit_by_reason": dict(Counter(it.unfit_reason for it in unfit)),
    }


def _table(rows: Iterable[list], header: list[str]) -> str:
    rows = [[str(c) for c in r] for r in rows]
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(header)]
    line = "  ".join(h.ljust(w) for h, w in zip(header, widths))
    out = [line, "-" * len(line)]
    out += ["  ".join(c.ljust(w) for c, w in zip(r, widths)) for r in rows]
    return "\n".join(out)


def format_plan(packer, max_rows_per_bin: int | None = None) -> str:
    """Human-readable loading instructions (one table per bin) plus the overflow."""
    parts = []
    s = summary(packer)
    if s["bins_used"] > 1 or s["total_cost"]:
        fleet = ", ".join(f"{n} x {name}" for name, n in s["containers_by_type"].items())
        head = f"Fleet: {fleet}"
        if s["total_cost"]:
            head += f" - total cost {s['total_cost']:,.2f}"
        if s["loaded_value"]:
            head += f", cargo value {s['loaded_value']:,.2f}, profit {s['profit']:,.2f}"
        parts.append(head)
    by_bin = defaultdict(list)
    for row in loading_plan(packer):
        by_bin[row["bin_index"]].append(row)
    info = {b["bin_index"]: b for b in s["bins"]}
    for b_index, rows in by_bin.items():
        b = info[b_index]
        head = (f"== {b['bin']} (bin {b_index}): {b['items']} items, {b['volume_utilization']:.1%} of volume, "
                f"{b['weight']:.1f} weight" + (f", value {b['value']:.2f}" if b["value"] else "")
                + (f", cost {b['cost']:,.2f}" if b["cost"] else "") + " ==")
        shown = rows if max_rows_per_bin is None else rows[:max_rows_per_bin]
        shapes = any(r["shape"] != "box" for r in rows)  # column only for plans with shaped items
        table = _table(([r["step"], r["item"]] + ([r["shape"]] if shapes else []) +
                        [f"({r['x']}, {r['y']}, {r['z']})",
                         f"{r['length_x']} x {r['height_y']} x {r['depth_z']}", r["rotation"],
                         " ".join(map(str, r["rests_on"])) or "floor"] for r in shown),
                       ["step", "item"] + (["shape"] if shapes else []) +
                       ["position (x, y, z)", "size as placed", "rotation", "rests on"])
        more = f"\n... {len(rows) - len(shown)} more steps" if len(shown) < len(rows) else ""
        parts.append(f"{head}\n{table}{more}")
    unfit = list(packer.get_unfit_items())
    if unfit:
        reasons = Counter(it.unfit_reason for it in unfit)
        lines = [f"== Not loaded: {len(unfit)} items =="]
        lines += [f"  {count:5d} x {reason}" for reason, count in reasons.most_common()]
        parts.append("\n".join(lines))
    if getattr(packer, "crates", None) is not None:
        from .crates import format_crates

        parts.append(format_crates(packer))
    return "\n\n".join(parts)
