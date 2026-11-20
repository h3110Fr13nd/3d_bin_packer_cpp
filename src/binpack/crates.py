"""Crates: boxes (or trunks, small containers) that are filled with goods and
loaded into the shipping containers like any other box.

A crate type has outer dimensions (what it takes in the container) and inner
dimensions (the space for goods). One crate holds one kind of goods:

* shaped goods (sphere, pyramid, cone, cylinder) of one shape and one size,
  in the densest pattern for the shape (see :mod:`binpack.bulk`), or
* boxes of any sizes, packed like a small container, loaded from the top.

Crates never mix consignments (``Item.group``). ``Item.crate_required=True``
items always travel in a crate. Other items are loaded loose, or crated when
that takes less container space: shaped goods pack much denser in a crate
than loose (where each takes its whole box), and any item rides in the free
space of a crate that is travelling anyway.

``pack_with_crates(packer, crate_types)`` fills the crates, then loads crates
and loose items with a copy of ``packer`` (its containers, container types and
settings): fleet planning, handling rules, loading sequence all apply. The
result reads like a packed Packer, so reports, ``validate`` and every picture
function take it; pictures show the crates open, with their contents.
"""
from __future__ import annotations

import math
import re
from collections import Counter, OrderedDict
from dataclasses import dataclass, field, replace

import numpy as np

import pybinding as _core

from . import _shapes
from .bulk import BulkPiece, bulk_layout, solid_volume

CRATE_COLOR = "#b5895a"


@dataclass
class CrateType:
    """A kind of crate (or trunk). Dimensions are (width, height, depth) like ``Bin``.

    tare_weight: the empty crate. max_weight: most weight of goods it takes (0 = no limit).
    cost: cost of using one. count: how many are available (None = as many as needed).
    upright / stackable / max_load / floor_only: how the crate itself may be loaded
    (``Item.upright``, ``not Item.disable_stacking``, ``Item.stuffing_max_weight``,
    ``Item.bottom_load_only``).
    inner_offset: corner of the inner space from the outer corner (None = centred).

    open_top: a loading crate (see :func:`LoadingCrate`): a base only, no walls
    or lid. Its height is the container's; ``base_height`` is from the ground to
    its floor. Give it footprints (width, depth); ``height`` fixes the column
    height, else the lowest container of the packer is used.
    """

    name: str
    outer: tuple
    inner: tuple
    tare_weight: float = 0.0
    max_weight: float = 0.0
    cost: float = 0.0
    count: int | None = None
    upright: bool = True
    stackable: bool = True
    max_load: float = 0.0
    inner_offset: tuple | None = None
    floor_only: bool = False
    open_top: bool = False
    base_height: float = 0.0
    height: int | None = None

    def __post_init__(self):
        if self.open_top:
            self._open_top_sizes()
        else:
            self.outer = tuple(int(x) for x in self.outer)
            self.inner = tuple(int(x) for x in self.inner)
            if len(self.outer) != 3 or len(self.inner) != 3 or min(self.inner) <= 0:
                raise ValueError(f"crate type '{self.name}': outer and inner need three positive sizes")
            if self.inner_offset is None:
                self.inner_offset = tuple((o - i) / 2 for o, i in zip(self.outer, self.inner))
        self.inner_offset = tuple(float(x) for x in self.inner_offset)
        if self.resolved and any(off < 0 or off + i > o
                                 for off, i, o in zip(self.inner_offset, self.inner, self.outer)):
            raise ValueError(f"crate type '{self.name}': the inner space {self.inner} does not fit in {self.outer}")
        if self.count is not None and self.count < 0:
            raise ValueError(f"crate type '{self.name}': count must be >= 0 or None")

    def _open_top_sizes(self):
        """Footprints (width, depth) -> (width, height, depth); height None until the column height is known."""
        def sizes(dims, what):
            dims = tuple(dims)
            if len(dims) == 2:
                dims = (dims[0], None, dims[1])
            if len(dims) != 3 or min(dims[0], dims[2]) <= 0:
                raise ValueError(f"loading crate '{self.name}': {what} needs a (width, depth) footprint")
            return tuple(None if x is None else int(x) for x in dims)

        self.outer, self.inner = sizes(self.outer, "outer"), sizes(self.inner, "inner")
        self.base_height = float(self.base_height)
        if self.base_height < 0:
            raise ValueError(f"loading crate '{self.name}': base_height must be >= 0")
        off = self.inner_offset
        if off is None:
            off = ((self.outer[0] - self.inner[0]) / 2, (self.outer[2] - self.inner[2]) / 2)
        off = tuple(off)
        self.inner_offset = (off[0], self.base_height, off[-1])  # (x, z) or (x, y, z): the floor is the base
        if any(o < 0 or o + i > out for o, i, out in ((off[0], self.inner[0], self.outer[0]),
                                                     (off[-1], self.inner[2], self.outer[2]))):
            raise ValueError(f"loading crate '{self.name}': the inner footprint does not fit in the outer one")
        column = self.outer[1] if self.outer[1] is not None else self.height
        if column is not None and column - self.base_height <= 0:
            raise ValueError(f"loading crate '{self.name}': no room above the base")

    @property
    def resolved(self) -> bool:
        """False for a loading crate whose height is not known yet."""
        return self.outer[1] is not None

    def with_height(self, height: int) -> "CrateType":
        """This loading crate with its column `height` (ground to container ceiling)."""
        height = int(height)
        if height - self.base_height <= 0:
            raise ValueError(f"loading crate '{self.name}': a column of {height} leaves no room above the base")
        inner_height = int(math.floor(height - self.base_height))
        return replace(self, outer=(self.outer[0], height, self.outer[2]),
                       inner=(self.inner[0], inner_height, self.inner[2]),
                       inner_offset=(self.inner_offset[0], self.inner_offset[2]))

    @property
    def outer_volume(self) -> float:
        return float(np.prod(self.outer))

    def inner_bin(self, cost: float = 0.0):
        return _core.Bin(self.name, *self.inner, max_weight=self.max_weight, cost=cost)


def LoadingCrate(name, outer, inner, base_height, tare_weight=0.0, max_weight=0.0, cost=0.0, count=None,
                 inner_offset=None, height=None) -> CrateType:
    """A loading crate: a base on wheels, no walls, no lid (a :class:`CrateType` with ``open_top``).

    outer, inner: footprints (width, depth); the base is a little bigger than the
    space for goods. base_height: from the ground to the floor for goods.
    Goods stack up to the container ceiling, so the crate takes the full height:
    it stands on the container floor, nothing goes on top of it, and it is never tipped.
    inner_offset: (x, z) of the goods' footprint on the base (None = centred).
    height: column height (None = the lowest container height the packer can use).
    """
    return CrateType(name, outer, inner, tare_weight=tare_weight, max_weight=max_weight, cost=cost, count=count,
                     upright=True, stackable=False, floor_only=True, inner_offset=inner_offset, open_top=True,
                     base_height=base_height, height=height)


@dataclass
class Crate:
    """One filled crate. ``contents`` are in the crate's inner space (origin at
    the inner back-bottom-left corner); ``item`` is what the container packer loads."""

    index: int
    type: CrateType
    name: str
    contents: list
    pattern: str
    group: str = ""
    item: object = None
    _bin: object = None          # the crate packer's bin, for crates of boxes

    @property
    def kind(self) -> str:
        """"box" or the shape of the goods."""
        return _shapes.shape_name(self.contents[0]) if self.contents else "box"

    @property
    def goods_weight(self) -> float:
        return float(sum(it.weight for it in self.contents))

    @property
    def weight(self) -> float:
        return self.type.tare_weight + self.goods_weight

    @property
    def fill(self) -> float:
        """Share of the inner space taken by the goods themselves."""
        goods = sum(solid_volume(it) for it in self.contents)
        return goods / float(np.prod(self.type.inner))

    def summary(self) -> str:
        """e.g. "24 x ball (300x300x300 sphere), 3 x vase (250x450x250)"."""
        names = Counter(_label(it) for it in self.contents)
        return ", ".join(f"{n} x {name}" for name, n in names.most_common())

    def placed_contents(self, crate_item) -> list:
        """The contents in container coordinates, for the crate as the container packer placed it."""
        axes = _shapes._AXES[crate_item.get_rotation_type()]  # container axis j <- crate axis axes[j]
        origin = np.array(crate_item.get_position(), dtype=float)
        offset = np.array(self.type.inner_offset)
        out = []
        for it in self.contents:
            lo = offset + np.array(it.get_position(), dtype=float)
            dims = np.array(it.get_dimension(), dtype=float)
            own = _shapes._AXES[it.get_rotation_type()]
            rotation = _ROTATION_OF[tuple(own[a] for a in axes)]
            out.append(_PlacedContent(it, self, origin + lo[list(axes)], dims[list(axes)], rotation))
        return out


_ROTATION_OF = {axes: r for r, axes in _shapes._AXES.items()}


def _label(it) -> str:
    """Product name (without its running number), size and shape."""
    shape = "" if it.shape == _core.Shape.BOX else f" {_shapes.shape_name(it)}"
    name = re.sub(r"[\s#_-]*\d+$", "", it.name) or it.name
    return f"{name} ({it.width}x{it.height}x{it.depth}{shape})"


class _PlacedContent:
    """A crate's content item where it ends up in the container (reads like a packed Item)."""

    carton = False

    def __init__(self, item, crate, position, dims, rotation):
        self._item, self.crate = item, crate
        self.name, self.shape = item.name, item.shape
        self.width, self.height, self.depth = item.width, item.height, item.depth
        self.weight, self.value, self.color = item.weight, item.value, item.color
        self.group, self.priority = item.group, item.priority
        self.inverted = bool(getattr(item, "inverted", False))
        self.crate_index = -1
        self._position, self._dims, self._rotation = tuple(position), [float(x) for x in dims], rotation

    def get_name(self):
        return self.name

    def get_position(self):
        return self._position

    def get_dimension(self):
        return self._dims

    def get_rotation_type(self):
        return self._rotation

    def get_volume(self):
        return solid_volume(self._item)


class _CrateBin:
    """A container of a crate plan: the packed Bin, plus the crates it refers to."""

    def __init__(self, bin_, crates):
        self._bin, self.crates = bin_, crates

    def __getattr__(self, name):
        return getattr(self._bin, name)

    def __repr__(self):
        return repr(self._bin)


@dataclass
class CratePlan:
    """Result of :func:`pack_with_crates`. Reads like a packed ``Packer``
    (``get_bins``, ``get_items``, ``get_unfit_items``, ...). The top-level
    items are crates (``item.crate_index >= 0``, see ``crates``) and loose goods."""

    packer: object
    crates: list
    crate_types: list
    not_crated: list = field(default_factory=list)  # crate_required items no crate could take
    total_goods: int = 0                              # items given to pack_with_crates

    def get_bins(self):
        return [_CrateBin(b, self.crates) for b in self.packer.get_bins()]

    def get_items(self):
        return self.packer.get_items()

    def get_unfit_items(self):
        return list(self.packer.get_unfit_items()) + list(self.not_crated)

    def crate_of(self, item):
        """The Crate a loaded (or unfit) crate item stands for, else None."""
        return self.crates[item.crate_index] if getattr(item, "crate_index", -1) >= 0 else None

    def unloaded_goods(self) -> list:
        """Every item that does not ship: loose ones left over, contents of crates left over, uncrated ones."""
        out = []
        for it in self.get_unfit_items():
            crate = self.crate_of(it)
            out += list(crate.contents) if crate else [it]
        return out

    def __getattr__(self, name):  # loading_access, min_support_ratio, get_total_cost, get_bin_types, ...
        if name in ("packer", "crates", "not_crated", "crate_types", "total_goods"):
            raise AttributeError(name)
        return getattr(self.packer, name)


# ------------------------------------------------------------ crate filling --

class _Stock:
    """Crates still available per type."""

    def __init__(self, types):
        self.left = [math.inf if t.count is None else t.count for t in types]


def _group_key(item):
    if item.shape == _core.Shape.BOX:
        return (item.group, "box")
    return (item.group, item.shape.name, item.width, item.height, item.depth)


def _plan_counts(n, caps, types, stock_left):
    """Crates for n pieces with per-type capacities: full crates of one type,
    the rest in the cheapest (then smallest) crate that takes it, repeated
    while crates run out. Returns [(type, pieces)], using up to the stock."""
    usable = [k for k, c in enumerate(caps) if c > 0 and stock_left[k] > 0]
    best = None
    for first in usable:
        left = list(stock_left)
        plan, rest = [], n
        full = min(rest // caps[first], left[first])
        plan += [(first, caps[first])] * int(full)
        left[first] -= full
        rest -= full * caps[first]
        while rest > 0:
            fits = [k for k in usable if left[k] > 0 and caps[k] >= rest]
            if fits:
                k = min(fits, key=lambda k: (types[k].cost, types[k].outer_volume))
                plan.append((k, rest))
                left[k] -= 1
                rest = 0
            else:
                avail = [k for k in usable if left[k] > 0]
                if not avail:
                    break
                k = max(avail, key=lambda k: (caps[k], -types[k].outer_volume))
                plan.append((k, caps[k]))
                left[k] -= 1
                rest -= caps[k]
        placed = sum(p for _, p in plan)
        score = (-placed, sum(types[k].cost for k, _ in plan), sum(types[k].outer_volume for k, _ in plan), len(plan))
        if best is None or score < best[0]:
            best = (score, plan)
    return best[1] if best else []


def _fill_shaped(req, opt, types, stock, crate_optional):
    """Crates for one shape and size. Returns (crates as [(type, layout, items)], loose, not_crated)."""
    first = (req or opt)[0]
    template = _core.Item(first.name, first.width, first.height, first.depth,
                          allowed_rotations=list(first.allowed_rotations), shape=first.shape,
                          weight=max(it.weight for it in req + opt),
                          upright=any(it.upright for it in req + opt))
    layouts = [bulk_layout(template, t.inner_bin(), order="bottom") for t in types]
    caps = [lay.count if lay else 0 for lay in layouts]
    box_volume = float(first.width) * first.height * first.depth

    def option(n_crated):
        plan = _plan_counts(n_crated, caps, types, stock.left)
        crated = sum(p for _, p in plan)
        volume = sum(types[k].outer_volume for k, _ in plan)
        return plan, crated, volume

    options = []
    plan, crated, volume = option(len(req))
    free = sum(caps[k] - p for k, p in plan) if crate_optional else 0
    extra = min(free, len(opt)) if crated == len(req) else 0
    # Required items in crates, optional ones in their free slots, the rest loose.
    options.append((plan, crated + extra, volume + (len(opt) - extra) * box_volume))
    if crate_optional and opt:
        # Optional pieces crated too: all of them, or whole crates' worth (the rest loose).
        counts = {len(opt)} | {min(len(opt), m * c) for c in caps if c > 0
                               for m in range(1, -(-len(opt) // c) + 1)}
        for x in sorted(counts):
            plan, crated, volume = option(len(req) + x)
            if crated >= len(req):
                options.append((plan, crated, volume + (len(req) + len(opt) - crated) * box_volume))
    # Least container space (crates + loose boxes), then cheapest crates, then fewest.
    plan, crated, _ = min(options, key=lambda o: (o[2], sum(types[k].cost for k, _ in o[0]), len(o[0])))

    goods = req + opt
    crates, pos = [], 0
    filled = sum(p for _, p in plan)
    for k, n in plan:
        if pos >= min(crated, filled):
            break
        n = min(n, min(crated, filled) - pos)
        stock.left[k] -= 1
        crates.append((k, layouts[k], goods[pos:pos + n]))
        pos += n
    rest = goods[pos:]
    not_crated = [it for it in rest if it.crate_required]
    loose = [it for it in rest if not it.crate_required]
    return crates, loose, not_crated


def _crate_packer(packer, fixed_bins=None, bin_types=None):
    p = _core.Packer(fill_order=_core.FillOrder.BOTTOM_BACK_LEFT, loading_access=_core.LoadingAccess.TOP,
                     min_support_ratio=packer.min_support_ratio, optimize=packer.optimize)
    for b in fixed_bins or []:
        p.add_bin(b)
    for b, count in bin_types or []:
        p.add_bin_type(b, count)
    return p


def _fill_boxes(req, opt, types, stock, packer, crate_optional):
    """Crates for boxes (any sizes) of one consignment: the crate packer books
    the cheapest crates for the required items (by outer volume when crates are
    free), then optional items fill the free space. Returns (bins, loose, not_crated)."""
    if not req:
        return [], list(opt), []
    source = list(req) + list(opt)
    priced = any(t.cost > 0 for t in types)
    kinds = [(t.inner_bin(t.cost if priced else t.outer_volume / 1e9), None if math.isinf(left) else int(left))
             for t, left in zip(types, stock.left) if left > 0]
    boost = max(0, max((it.priority for it in opt), default=0) - min(it.priority for it in req) + 1)

    def add(crate_packer, k, required_first=False):
        it = source[k]
        # Inside the crate packer the item is already "in a crate", and its consignment may fill several
        # crates (the crates carry the group into the container); crate_index remembers where it came from.
        saved = it.crate_required, it.crate_index, it.priority, it.group
        it.crate_required, it.crate_index, it.group = False, k, ""
        if required_first and k < len(req):
            it.priority += boost
        crate_packer.add_item(it)  # a copy
        it.crate_required, it.crate_index, it.priority, it.group = saved

    def restore(items):
        for it in items:
            src = source[it.crate_index]
            it.crate_required, it.crate_index, it.priority, it.group = src.crate_required, -1, src.priority, src.group
        return items

    first = _crate_packer(packer, bin_types=kinds)
    for k in range(len(req)):
        add(first, k)
    first.pack()
    chosen = [b for b in first.get_bins() if b.get_items()]
    for b in chosen:
        restore(b.get_items())
    not_crated = [source[u.crate_index] for u in first.get_unfit_items()]
    loose = list(opt)
    if crate_optional and opt and chosen:
        # Same crates again: required items first (higher priority), optional ones where room is left.
        again = _crate_packer(packer, fixed_bins=[
            _core.Bin(b.get_name(), b.get_width(), b.get_height(), b.get_depth(), max_weight=b.max_weight)
            for b in chosen])
        for k in range(len(source)):
            add(again, k, required_first=True)
        again.pack()
        unfit = [source[u.crate_index] for u in again.get_unfit_items()]
        if sum(u.crate_required for u in unfit) <= len(not_crated):
            chosen = [b for b in again.get_bins() if b.get_items()]
            for b in chosen:
                restore(b.get_items())
            not_crated = [u for u in unfit if u.crate_required]
            loose = [u for u in unfit if not u.crate_required]
    for b in chosen:
        stock.left[_type_of(b, types)] -= 1
    return chosen, loose, not_crated


def _fits(item, crate_type):
    for r in item.get_effective_rotations():
        dims = _core_rotated(item, r)
        if all(d <= s for d, s in zip(dims, crate_type.inner)):
            return crate_type.max_weight <= 0 or item.weight <= crate_type.max_weight
    return False


def _core_rotated(item, rotation):
    dims = (item.width, item.height, item.depth)
    return tuple(dims[a] for a in _shapes._AXES[rotation])


class _NotCrated:
    """An item that had to travel in a crate but no crate could take it."""

    def __init__(self, item, reason):
        self._item, self.unfit_reason = item, reason

    def __getattr__(self, name):
        return getattr(self._item, name)

    def __repr__(self):
        return f"<not crated: {self._item.name} ({self.unfit_reason})>"


def pack_with_crates(packer, crate_types, crate_optional: bool = True) -> CratePlan:
    """Fills crates with the packer's items, then loads crates and loose items.

    packer: a Packer with items, containers (``add_bin`` / ``add_bin_type``)
    and settings; it is left unchanged (a copy does the loading).
    crate_types: list of :class:`CrateType` (distinct names).
    crate_optional: also crate items that don't require it, when that saves
    container space (False: only ``crate_required`` items go in crates).
    """
    types = [_resolve(t, packer) for t in crate_types]
    if not types:
        raise ValueError("no crate types given")
    if len({t.name for t in types}) != len(types):
        raise ValueError("crate types need distinct names")
    stock = _Stock(types)
    groups: "OrderedDict[tuple, tuple[list, list]]" = OrderedDict()
    for it in packer.items:  # copies
        groups.setdefault(_group_key(it), ([], []))[0 if it.crate_required else 1].append(it)

    crates, loose, not_crated = [], [], []
    counters = Counter()

    def new_crate(k, contents, pattern, group, bin_=None):
        counters[k] += 1
        crates.append(Crate(len(crates), types[k], f"{types[k].name} #{counters[k]}", contents, pattern, group,
                            _bin=bin_))

    # Bigger groups first: they gain most from crates in limited stock.
    order = sorted(groups, key=lambda key: -sum(float(i.width) * i.height * i.depth for i in sum(groups[key], [])))
    for key in order:
        req, opt = groups[key]
        if key[1] == "box":
            bins, rest, failed = _fill_boxes(req, opt, types, stock, packer, crate_optional)
            for b in bins:
                new_crate(_type_of(b, types), b.get_items(), "packed boxes", key[0], bin_=b)
        else:
            filled, rest, failed = _fill_shaped(req, opt, types, stock, crate_optional)
            for k, layout, goods in filled:
                new_crate(k, [BulkPiece(it, it.name, layout.rotation, pos, flip)
                              for it, pos, flip in zip(goods, layout.positions, layout.inverted)],
                          layout.pattern, key[0])
        loose += rest
        for it in failed:
            fits = any(_fits(it, t) for t in types)
            not_crated.append(_NotCrated(it, "no crate left: all available crates are in use" if fits
                                         else "too large (or too heavy) for every crate"))

    loader = _copy_packer(packer)
    for crate in crates:
        t = crate.type
        # "This side up" goods keep their crate upright too.
        upright = t.upright or any(getattr(it, "upright", False) for it in crate.contents)
        item = _core.Item(crate.name, *t.outer, weight=crate.weight, upright=upright,
                          disable_stacking=not t.stackable, stuffing_max_weight=t.max_load,
                          bottom_load_only=t.floor_only,
                          value=float(sum(it.value for it in crate.contents)),
                          priority=max((it.priority for it in crate.contents), default=0), group=crate.group)
        item.crate_index = crate.index
        crate.item = item
        loader.add_item(item)
    for it in loose:
        loader.add_item(it)
    loader.pack()
    return CratePlan(loader, crates, types, not_crated, total_goods=len(packer.items))


def _resolve(crate_type, packer):
    """Loading crates get their height: given, or that of the lowest container the packer can use."""
    if crate_type.resolved:
        return crate_type
    if crate_type.height is not None:
        return crate_type.with_height(crate_type.height)
    heights = [b.get_height() for b in packer.bins if b.type_index < 0]
    heights += [t.bin.get_height() for t in packer.get_bin_types() if t.count != 0]
    if not heights:
        raise ValueError(f"loading crate '{crate_type.name}': add containers to the packer first "
                         "(its height is the container's), or give it a height")
    return crate_type.with_height(min(heights))


def _type_of(bin_, types):
    """Crate type of a crate packer bin (booked types are named '<type> #k')."""
    name = bin_.get_name()
    for k, t in enumerate(types):
        if name == t.name or name.startswith(t.name + " #"):
            return k
    raise KeyError(name)


def _copy_packer(packer):
    copy = _core.Packer(fill_order=packer.fill_order, min_support_ratio=packer.min_support_ratio,
                        non_stackable_on_top=packer.non_stackable_on_top, optimize=packer.optimize,
                        loading_access=packer.loading_access, objective=packer.objective,
                        fleet_goal=packer.fleet_goal)
    fresh = lambda b: _core.Bin(b.get_name(), b.get_width(), b.get_height(), b.get_depth(),  # noqa: E731
                                max_weight=b.max_weight, image=b.image, description=b.description, id=b.id,
                                cost=b.cost)
    for b in packer.bins:
        if b.type_index < 0:  # containers added with add_bin (not ones booked by an earlier fleet plan)
            copy.add_bin(fresh(b))
    for t in packer.get_bin_types():
        copy.add_bin_type(fresh(t.bin), t.count)
    return copy


# ------------------------------------------------------------------ reports --

def crate_manifest(plan: CratePlan) -> list[dict]:
    """One row per item inside a crate: which crate, where the crate is, and where the item is in it."""
    where = {}
    for b_index, b in enumerate(plan.get_bins()):
        for step, it in enumerate(b.get_items(), 1):
            if it.crate_index >= 0:
                where[it.crate_index] = (b.get_name(), step)
    rows = []
    for crate in plan.crates:
        container, step = where.get(crate.index, ("not loaded", None))
        for k, it in enumerate(crate.contents, 1):
            x, y, z = it.get_position()
            rows.append({"crate": crate.name, "crate_type": crate.type.name, "container": container,
                         "container_step": step, "crate_step": k, "item": it.name,
                         "shape": _shapes.shape_name(it), "x": round(float(x), 1), "y": round(float(y), 1),
                         "z": round(float(z), 1), "rotation": it.get_rotation_type().name,
                         "tip_down": bool(getattr(it, "inverted", False)), "weight": it.weight})
    return rows


def format_crates(plan: CratePlan) -> str:
    """Crate contents, for :func:`binpack.format_plan`."""
    where = {}
    for b in plan.get_bins():
        for step, it in enumerate(b.get_items(), 1):
            if it.crate_index >= 0:
                where[it.crate_index] = f"{b.get_name()} step {step}"
    lines = [f"== Crates: {len(plan.crates)} =="]
    for c in plan.crates:
        kind = (f" [loading crate, open to {c.type.outer[1]}, base {c.type.base_height:g}]"
                if c.type.open_top else "")
        lines.append(f"  {c.name}{kind} ({where.get(c.index, 'NOT LOADED')}): {c.summary()} - {c.pattern}, "
                     f"{c.fill:.0%} of the inside, {c.weight:,.1f} weight")
    if plan.not_crated:
        reasons = Counter(it.unfit_reason for it in plan.not_crated)
        lines += [f"  not crated: {n} x {r}" for r, n in reasons.items()]
    return "\n".join(lines)
