"""Pictures of packed bins and fleets: single views, loading steps and animations.

Rendering uses an orthographic camera and an exact painter's algorithm: for
every pair of boxes whose outlines overlap on screen, the one in front is
determined geometrically and boxes are drawn in a topological order of that
relation. (Sorting by average depth - what generic 3D plotting does - draws
boxes of different sizes in the wrong order.)

Shaped items (``Item.shape``: sphere, pyramid, cone, cylinder) are packed as
their box - a thin carton - and drawn as the real shape inside that carton,
whose outline is drawn faintly (``cartons=False`` hides it). The shapes are
convex and lie inside their boxes, so the same back-to-front order of boxes
draws them correctly.

Requires matplotlib (``pip install matplotlib``).
"""
from __future__ import annotations

import heapq
import re
from collections import OrderedDict

import numpy as np

from . import _shapes
from ._geometry import boxes_array, row_blocks

DEFAULT_VIEW = (55.0, 28.0)  # azimuth from the door towards the right side, elevation (degrees)
_DEFAULT_COLOR = "#000000"
_SHADE = np.array([0.80, 1.00, 0.64])  # brightness of x-, y- (top) and z-facing sides


def _plt():
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError("binpack.render needs matplotlib: pip install matplotlib") from exc
    return plt


# ---------------------------------------------------------------- geometry --

def camera(view=DEFAULT_VIEW):
    """Unit vectors (towards_camera, screen_right, screen_up) for (azimuth, elevation).

    Azimuth 0 looks from the door (+z) straight into the bin; 90 looks from
    the right side (+x). Elevation is the angle above the horizon.
    """
    azim, elev = np.radians(view[0]), np.radians(view[1])
    v = np.array([np.cos(elev) * np.sin(azim), np.sin(elev), np.cos(elev) * np.cos(azim)])
    right = np.cross([0.0, 1.0, 0.0], v)
    if np.linalg.norm(right) < 1e-9:  # looking straight down
        right = np.array([1.0, 0.0, 0.0])
    right /= np.linalg.norm(right)
    up = np.cross(v, right)
    return v, right, up


def _front_pairs(lo, hi, rows, v, eps, cols=None):
    """For pieces ``rows`` against all pieces: (r, j) where row r is in front of
    piece j and their screen outlines overlap.

    Piece i hides part of piece j iff a line parallel to v passes through both,
    i.e. iff the line {t*v} crosses the interior of the Minkowski difference
    box_i - box_j; t > 0 means i is the one closer to the camera.
    """
    cols = np.arange(len(lo)) if cols is None else np.asarray(cols)
    dlo = lo[rows, None, :] - hi[None, cols, :]
    dhi = hi[rows, None, :] - lo[None, cols, :]
    t_lo = np.full(dlo.shape[:2], -np.inf)
    t_hi = np.full(dlo.shape[:2], np.inf)
    ok = np.ones(dlo.shape[:2], dtype=bool)
    for k in range(3):
        if abs(v[k]) < 1e-12:
            ok &= (dlo[..., k] < -eps) & (dhi[..., k] > eps)
            continue
        a, b = dlo[..., k] / v[k], dhi[..., k] / v[k]
        t_lo = np.maximum(t_lo, np.minimum(a, b))
        t_hi = np.minimum(t_hi, np.maximum(a, b))
    tol = eps / max(1e-12, float(np.abs(v).max()))
    front = ok & (t_lo < t_hi - tol) & (t_lo >= -tol)
    front &= np.asarray(rows)[:, None] != cols[None, :]
    r_idx, c_idx = np.nonzero(front)
    return r_idx, cols[c_idx]


def draw_order(lo, hi, v, max_splits: int = 500, pairs=None, whole=None):
    """Back-to-front drawing order of non-intersecting axis-aligned boxes seen along -v.

    Returns ``(owner, piece_lo, piece_hi)``: pieces to draw in this order and
    the box each belongs to. Boxes normally stay whole; the rare cyclic overlaps
    (A hides B hides C hides A) are resolved by splitting a box of the cycle
    along a face plane of another member, as in Newell's algorithm.

    pairs: (front, back) index pairs computed by the caller instead of the box
    geometry, for shapes packed closer than their boxes (bulk loads, whose
    boxes intersect). Boxes are then never split; a cycle is broken at its
    farthest box.
    whole: boolean mask of boxes that must not be split (crates drawn with
    their contents); a cycle of only such boxes is broken at its farthest box.
    """
    plo = np.asarray(lo, dtype=float).reshape(-1, 3)
    phi = np.asarray(hi, dtype=float).reshape(-1, 3)
    owner = list(range(len(plo)))
    eps = 1e-9 * max(1.0, float(np.abs(phi).max(initial=1.0)))
    succ: list[set[int]] = [set() for _ in owner]
    pred: list[set[int]] = [set() for _ in owner]

    def link(rows):
        r_idx, j_idx = _front_pairs(plo, phi, np.asarray(rows), v, eps)
        for r, j in zip(r_idx, j_idx):  # rows[r] in front of j: draw j first
            i = rows[r]
            succ[j].add(i)
            pred[i].add(j)

    fixed = pairs is not None
    release = False  # break cycles by releasing their farthest box
    if fixed:
        for i, j in pairs:  # i in front of j: draw j first
            succ[int(j)].add(int(i))
            pred[int(i)].add(int(j))
    else:
        for i0, i1 in row_blocks(len(plo), 512):
            link(list(range(i0, i1)))

    for _ in range(max_splits + 1):
        n = len(plo)
        depth = ((plo + phi) / 2.0) @ v
        pending = np.array([len(pred[i]) for i in range(n)], dtype=np.int64)
        heap = [(depth[i], i) for i in range(n) if pending[i] == 0]
        heapq.heapify(heap)
        order, done = [], np.zeros(n, dtype=bool)
        while heap or ((fixed or release) and len(order) < n):
            if not heap:  # a cycle: release its farthest box
                left = np.nonzero(~done)[0]
                i = int(left[np.argmin(depth[left])])
                pending[i] = 0
                heapq.heappush(heap, (depth[i], i))
            _, i = heapq.heappop(heap)
            if done[i]:
                continue
            order.append(i)
            done[i] = True
            for j in succ[i]:
                pending[j] -= 1
                if pending[j] == 0 and not done[j]:
                    heapq.heappush(heap, (depth[j], j))
        if len(order) == n:
            return np.array([owner[i] for i in order], dtype=np.int64), plo[order], phi[order]

        # Extract a cycle: every stuck piece has a stuck predecessor.
        stuck = {i for i in range(n) if pending[i] > 0}
        cur, walk = next(iter(stuck)), []
        while cur not in walk:
            walk.append(cur)
            cur = next(j for j in pred[cur] if j in stuck)
        cycle = walk[walk.index(cur):]
        if _ == max_splits:  # give up: break the cycle at the farthest piece
            break
        # Split a member along a face plane of another member that cuts through it.
        cut = None
        splittable = [c for c in cycle if whole is None or not whole[owner[c]]]
        if not splittable:
            release = True
            continue
        for c in sorted(splittable, key=lambda i: -np.prod(phi[i] - plo[i])):
            for d in cycle:
                for k in range(3):
                    for x in (plo[d, k], phi[d, k]):
                        if plo[c, k] + eps < x < phi[c, k] - eps:
                            cut = (c, k, x)
                            break
                    if cut: break
                if cut: break
            if cut: break
        if cut is None:
            c = splittable[0]
            k = int(np.argmax(phi[c] - plo[c]))
            cut = (c, k, (plo[c, k] + phi[c, k]) / 2.0)
        c, k, x = cut
        new = len(plo)
        piece_lo, piece_hi = plo[c].copy(), phi[c].copy()
        piece_lo[k] = x
        phi[c, k] = x
        plo = np.vstack([plo, piece_lo])
        phi = np.vstack([phi, piece_hi])
        owner.append(owner[c])
        for j in succ[c]:
            pred[j].discard(c)
        for j in pred[c]:
            succ[j].discard(c)
        succ[c], pred[c] = set(), set()
        succ.append(set())
        pred.append(set())
        link([c, new])  # the new pieces in front of others
        others = np.arange(len(plo))
        r_idx, j_idx = _front_pairs(plo, phi, others, v, eps, cols=[c, new])  # others in front of them
        for r, j in zip(r_idx, j_idx):
            i = int(others[r])
            if i not in (c, new):
                succ[j].add(i)
                pred[i].add(j)

    # Fallback (only after max_splits): farthest-first for what is left.
    depth = ((plo + phi) / 2.0) @ v
    order = list(np.argsort(depth))
    return np.array([owner[i] for i in order], dtype=np.int64), plo[order], phi[order]


def _faces(lo, hi, v):
    """Visible faces of each box: list of (axis, 4 corner points)."""
    faces = []
    for k in range(3):
        if abs(v[k]) < 1e-12:
            continue
        at = hi[k] if v[k] > 0 else lo[k]
        a, b = [x for x in range(3) if x != k]
        quad = []
        for ua, ub in ((0, 0), (1, 0), (1, 1), (0, 1)):
            p = np.empty(3)
            p[k] = at
            p[a] = hi[a] if ua else lo[a]
            p[b] = hi[b] if ub else lo[b]
            quad.append(p)
        faces.append((k, np.array(quad)))
    return faces


def _occluded(points, lo, hi, v, skip):
    """For each 3D point, is it hidden by a box (other than skip[i]) towards the camera?"""
    hidden = np.zeros(len(points), dtype=bool)
    lo = lo.astype(float)
    hi = hi.astype(float)
    for m, p in enumerate(points):
        t_lo = np.full(len(lo), 1e-6)
        t_hi = np.full(len(lo), np.inf)
        ok = np.ones(len(lo), dtype=bool)
        for k in range(3):
            if abs(v[k]) < 1e-12:
                ok &= (lo[:, k] < p[k]) & (p[k] < hi[:, k])
                continue
            a, b = (lo[:, k] - p[k]) / v[k], (hi[:, k] - p[k]) / v[k]
            t_lo = np.maximum(t_lo, np.minimum(a, b))
            t_hi = np.minimum(t_hi, np.maximum(a, b))
        hit = ok & (t_lo < t_hi)
        hit[skip[m]] = False
        hidden[m] = hit.any()
    return hidden


# ------------------------------------------------------------------ colours --

_PALETTE = ["#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#76b7b2", "#edc948", "#b07aa1", "#ff9da7",
            "#9c755f", "#bab0ac", "#86bcb6", "#d37295", "#a0cbe8", "#ffbe7d", "#8cd17d", "#f1ce63"]


def _type_key(item):
    dims = tuple(sorted((item.width, item.height, item.depth)))
    return re.sub(r"[\s#_-]*\d+$", "", item.name) or item.name, dims, _shapes.shape_name(item)


class Palette:
    """Item -> colour, shared by all bins of a plan so a product has one colour everywhere.

    color_by: "auto" (item colours if any is set, else item types), "color",
    "type", "group" or "priority".
    """

    def __init__(self, items, color_by: str = "auto"):
        items = list(items)
        if color_by == "auto":
            color_by = "color" if any(it.color not in ("", _DEFAULT_COLOR) for it in items) else "type"
        self.color_by = color_by
        self._colors: OrderedDict = OrderedDict()
        self._labels: dict = {}
        self._counts: dict = {}
        for it in items:
            key = self._key(it)
            if key not in self._colors:
                self._colors[key] = it.color if color_by == "color" else _PALETTE[len(self._colors) % len(_PALETTE)]
                self._labels[key] = self._label(it)
                self._counts[key] = 0
            self._counts[key] += 1

    def _key(self, it):
        if self.color_by == "color":
            return it.color
        if self.color_by == "group":
            return it.group or "(no group)"
        if self.color_by == "priority":
            return f"priority {it.priority}"
        return _type_key(it)

    def _label(self, it):
        if self.color_by == "type":
            shape = f" {_shapes.shape_name(it)}" if _shapes.is_shaped(it) else ""
            return f"{_type_key(it)[0]} {it.width}x{it.height}x{it.depth}{shape}"
        if self.color_by == "color":
            return None
        return self._key(it)

    def color(self, it) -> str:
        from matplotlib.colors import to_hex

        key = self._key(it)
        return to_hex(self._colors.get(key, _PALETTE[hash(key) % len(_PALETTE)]))

    def legend(self) -> "OrderedDict[str, str]":
        entries = OrderedDict()
        for key, color in self._colors.items():
            if self._labels.get(key):
                entries[f"{self._labels[key]} (x{self._counts[key]})"] = color
        return entries


# ------------------------------------------------------------------- drawing --

def _bin_size(bin_):
    return np.array([bin_.get_width(), bin_.get_height(), bin_.get_depth()], dtype=float)


def _corners(size):
    return np.array([[x, y, z] for x in (0, size[0]) for y in (0, size[1]) for z in (0, size[2])])


def _extent(bin_, proj):
    """Screen bounding box (xmin, xmax, ymin, ymax) of the bin outline."""
    pts = _corners(_bin_size(bin_)) @ proj
    return pts[:, 0].min(), pts[:, 0].max(), pts[:, 1].min(), pts[:, 1].max()


# Kinds of drawing primitives: a box face, facets of a shaped item, the
# outline (silhouette, rims, ridges) of a shaped item, edges of its carton.
_BOX_FACE, _SHAPE_FACET, _OUTLINE, _CARTON, _CRATE_WALL, _CRATE_EDGE, _OPEN_WALL, _OPEN_EDGE = range(8)
_LINES = (_OUTLINE, _CARTON, _CRATE_EDGE, _OPEN_EDGE)
_WALL_ALPHA = {_CRATE_WALL: 0.3, _OPEN_WALL: 0.12}  # closed crates; the open column of loading crates
_CRATE_RGB = np.array([0.87, 0.74, 0.55])  # crates: light wood, see-through
_CRATE_EDGE_COLOR = (0.42, 0.28, 0.13, 0.9)
_OPEN_EDGE_COLOR = (0.42, 0.28, 0.13, 0.4)
_EDGE_COLOR = (0.15, 0.15, 0.15, 0.55)
_OUTLINE_COLOR = (0.12, 0.12, 0.12, 0.8)
_CARTON_COLOR = (0.2, 0.2, 0.25, 0.3)
# Per kind. Facets of a shape are filled without antialiasing or edges: they
# tile seamlessly (antialiased neighbours leave hairlines), and the
# antialiased outline drawn over them keeps the silhouette smooth.
_LINE_WIDTHS = np.array([0.35, 0.0, 0.6, 0.5, 0.0, 0.9, 0.0, 0.6])
# Facets of a shape are drawn as one path per brightness level (far fewer
# paths for matplotlib); steps this small don't show as bands.
_SHADE_STEP = 0.02


def _camera_basis(v):
    """(v, right, up) for a viewing direction, as :func:`camera` builds them."""
    v = np.asarray(v, dtype=float)
    right = np.cross([0.0, 1.0, 0.0], v)
    if np.linalg.norm(right) < 1e-9:
        right = np.array([1.0, 0.0, 0.0])
    right /= np.linalg.norm(right)
    return v, right, np.cross(v, right)


def _convex_hull(points):
    """Counter-clockwise convex hull of 2D points (monotone chain)."""
    pts = np.unique(np.round(np.asarray(points, dtype=float), 9), axis=0)
    if len(pts) < 3:
        return pts

    def half(seq):
        out = []
        for p in seq:
            while len(out) >= 2 and ((out[-1][0] - out[-2][0]) * (p[1] - out[-2][1])
                                     - (out[-1][1] - out[-2][1]) * (p[0] - out[-2][0])) <= 0:
                out.pop()
            out.append(p)
        return out

    lower, upper = half(pts), half(pts[::-1])
    return np.array(lower[:-1] + upper[:-1])


def _inside_convex(hull, points, margin=0.0):
    """Are the points strictly inside the counter-clockwise convex polygon (by more than margin)?"""
    points = np.asarray(points, dtype=float).reshape(-1, 2)
    if len(hull) < 3:
        return np.zeros(len(points), dtype=bool)
    edge = np.roll(hull, -1, axis=0) - hull
    length = np.linalg.norm(edge, axis=1)
    rel = points[:, None, :] - hull[None]
    cross = (edge[None, :, 0] * rel[..., 1] - edge[None, :, 1] * rel[..., 0]) / np.maximum(length, 1e-300)
    return np.all(cross > margin, axis=1)


def _box_edge_table():
    """The 12 edges of a box as (corner a, corner b, adjacent faces): corners index
    ``_CORNER_BITS``, faces are (axis, side) with side 1 = the high end."""
    bits = np.array([[x, y, z] for x in (0, 1) for y in (0, 1) for z in (0, 1)])
    table = []
    for a in range(8):
        for b in range(a + 1, 8):
            diff = np.nonzero(bits[a] != bits[b])[0]
            if len(diff) == 1:
                table.append((a, b, tuple((k, int(bits[a][k])) for k in range(3) if k != diff[0])))
    return bits, table


_CORNER_BITS, _BOX_EDGES = _box_edge_table()


def _carton_edges(lo, hi, piece_lo, piece_hi, v, whole, eps=1e-12):
    """The 12 edges of the carton [lo, hi] (clipped to the piece unless ``whole``),
    split into (far, near) lists of segments: far edges lie behind the item's
    shape, near ones in front of it or beside it."""
    corners = lo + _CORNER_BITS * (hi - lo)
    far, near = [], []
    for a, b, faces in _BOX_EDGES:
        # Behind the shape when neither face the edge bounds faces the camera.
        faces_camera = any((v[k] > eps) if side else (v[k] < -eps) for k, side in faces)
        seg = (corners[a], corners[b]) if whole else _shapes.clip_segment(corners[a], corners[b], piece_lo, piece_hi)
        if seg is not None and not np.array_equal(seg[0], seg[1]):
            (near if faces_camera else far).append(seg)
    return far, near


def _polygons_path(polys):
    """One compound path of closed polygons: an (m, k, 2) array or a list of (k_i, 2) arrays."""
    from matplotlib.path import Path

    if isinstance(polys, np.ndarray):
        m, k, _ = polys.shape
        verts = np.concatenate([polys, polys[:, :1]], axis=1).reshape(-1, 2)
        codes = np.full((m, k + 1), Path.LINETO, dtype=Path.code_type)
        codes[:, 0], codes[:, -1] = Path.MOVETO, Path.CLOSEPOLY
        return Path(verts, codes.ravel())
    verts = np.concatenate([np.vstack([p, p[:1]]) for p in polys])
    codes = np.concatenate([[Path.MOVETO] + [Path.LINETO] * (len(p) - 1) + [Path.CLOSEPOLY] for p in polys])
    return Path(verts, codes.astype(Path.code_type))


def _segments_path(segments):
    """One path of separate line segments, (m, 2, 2)."""
    from matplotlib.path import Path

    segments = np.asarray(segments, dtype=float).reshape(-1, 2, 2)
    codes = np.tile(np.array([Path.MOVETO, Path.LINETO], dtype=Path.code_type), len(segments))
    return Path(segments.reshape(-1, 2), codes)


class _Scene:
    """Per-bin data reused across frames: boxes, their back-to-front order and
    their projected, shaded faces (or the shapes of shaped items)."""

    def __init__(self, bin_, v, cartons: bool = True):
        self.bin = bin_
        self.items = list(bin_.get_items())
        self.lo, self.hi = boxes_array(self.items)
        self._placed = {}
        self.crates = getattr(bin_, "crates", None)  # crate plans: items with crate_index >= 0 are crates
        is_crate = np.array([self._crate(i) is not None for i in range(len(self.items))], dtype=bool)
        # Loading crates are open to the ceiling: nothing is ever above them, so their box reaches it.
        self._goods_top = {}
        for i in np.nonzero(is_crate)[0]:
            if self._crate(i).type.open_top:
                self._goods_top[i] = float(self.hi[i][1])
                self.hi = self.hi.astype(float)
                self.hi[i, 1] = max(self.hi[i, 1], float(bin_.get_height()))
        self.order = draw_order(self.lo, self.hi, v, pairs=self._shape_pairs(v), whole=is_crate)
        self.cartons = cartons
        self._faces = None
        self._geom = None
        self._anchors = {}

    def _crate(self, i):
        k = getattr(self.items[i], "crate_index", -1)
        return self.crates[k] if self.crates is not None and k >= 0 else None

    def placed(self, i):
        if i not in self._placed:
            self._placed[i] = _shapes.place(self.items[i])
        return self._placed[i]

    def _shape_pairs(self, v):
        """For bulk loads (shapes packed closer than their boxes, so boxes
        intersect): (front, back) pairs of the shapes that overlap on screen.
        None when no boxes intersect: the box order is exact then."""
        lo, hi = self.lo.astype(float), self.hi.astype(float)
        n = len(lo)
        tol = 1e-6 * max(1.0, float(np.abs(hi).max(initial=1.0)))
        if not any(np.any(np.all((lo[i0:i1, None] < hi[None] - tol) & (lo[None] < hi[i0:i1, None] - tol), axis=2)
                          & ~np.eye(i1 - i0, n, i0, dtype=bool)) for i0, i1 in row_blocks(n, 512)):
            return None
        _, right, up = _camera_basis(v)
        proj = np.stack([right, up], axis=1)
        centre = (lo + hi) / 2 @ proj
        # Outline of each kind of piece on screen, around its box centre (bulk loads have one or two kinds).
        kinds, kind_of = {}, np.empty(n, dtype=np.int64)
        for i, it in enumerate(self.items):
            key = (it.shape, it.get_rotation_type(), tuple(it.get_dimension()), bool(getattr(it, "inverted", False)))
            if key not in kinds:
                placed = self.placed(i)
                kinds[key] = (len(kinds), _convex_hull((placed.vertices - (lo[i] + hi[i]) / 2) @ proj))
            kind_of[i] = kinds[key][0]
        hulls = [h for _, h in sorted(kinds.values(), key=lambda x: x[0])]
        # Screen boxes of the outlines for a quick first filter.
        ext = np.array([[h[:, 0].min(), h[:, 0].max(), h[:, 1].min(), h[:, 1].max()] for h in hulls])[kind_of]
        sx0, sx1 = centre[:, 0] + ext[:, 0], centre[:, 0] + ext[:, 1]
        sy0, sy1 = centre[:, 1] + ext[:, 2], centre[:, 1] + ext[:, 3]
        differences = {}
        result = []
        for i0, i1 in row_blocks(n, 512):
            near = ((sx0[i0:i1, None] < sx1[None]) & (sx0[None] < sx1[i0:i1, None]) &
                    (sy0[i0:i1, None] < sy1[None]) & (sy0[None] < sy1[i0:i1, None]))
            rows, cols = np.nonzero(near)
            rows = rows + i0
            keep = cols > rows
            rows, cols = rows[keep], cols[keep]
            # Outlines overlap iff the centre offset lies inside the Minkowski difference of the outlines.
            overlap = np.zeros(len(rows), dtype=bool)
            for ka in range(len(hulls)):
                for kb in range(len(hulls)):
                    sel = (kind_of[rows] == ka) & (kind_of[cols] == kb)
                    if not sel.any():
                        continue
                    if (ka, kb) not in differences:
                        # i at c_i + H_i meets j at c_j + H_j iff c_j - c_i lies in H_i - H_j.
                        diff = (hulls[ka][:, None, :] - hulls[kb][None, :, :]).reshape(-1, 2)
                        differences[(ka, kb)] = _convex_hull(diff)
                    overlap[sel] = _inside_convex(differences[(ka, kb)], centre[cols[sel]] - centre[rows[sel]],
                                                  margin=tol)
            rows, cols = rows[overlap], cols[overlap]
            for i, j in zip(rows.tolist(), cols.tolist()):
                apart = (hi[i] <= lo[j] + tol) | (hi[j] <= lo[i] + tol)
                if apart.any():  # boxes apart along an axis: the box order is exact
                    k = int(np.argmax(apart * np.abs(v)))
                    j_ahead = lo[j][k] >= hi[i][k] - tol
                    rel = (1 if j_ahead else -1) * (1 if v[k] > 0 else -1) if abs(v[k]) > 1e-12 else 0
                else:
                    rel = _shapes.in_front(self.placed(i), self.placed(j), v)
                if rel:
                    result.append((j, i) if rel > 0 else (i, j))
        return result

    def anchor(self, i, v):
        """Where the loading-step number of item i goes (a point on what is drawn)."""
        if i not in self._anchors:
            it = self.items[i]
            if _shapes.is_shaped(it):
                self._anchors[i] = _shapes.front_point(it, v)
            elif i in self._goods_top:  # a loading crate: on top of its goods
                crate = self._crate(i)
                goods = crate.placed_contents(it)
                top = max((p.get_position()[1] + p.get_dimension()[1] for p in goods),
                          default=self.lo[i][1] + crate.type.base_height)
                centre = (self.lo[i] + self.hi[i]) / 2.0
                centre[1] = top
                self._anchors[i] = centre
            else:
                lo, hi = self.lo[i], self.hi[i]
                face = 1 if v[1] > 0 else int(np.argmax(np.abs(v)))
                centre = (lo + hi) / 2.0
                centre[face] = hi[face] if v[face] > 0 else lo[face]
                self._anchors[i] = centre
        return self._anchors[i]

    def _shape_paths(self, i, piece_lo, piece_hi, whole, v, proj):
        """(kind, path, shade) of shaped item i inside one piece of its box, in drawing order:
        far carton edges, facets (one path per brightness), outline, near carton edges."""
        it = self.items[i]
        faces, normals, outline = _shapes.visible_parts(self.placed(i), v)
        shades = (normals ** 2) @ _SHADE  # box faces get exactly _SHADE[axis]
        levels = np.round(shades / _SHADE_STEP) * _SHADE_STEP
        far, near = (_carton_edges(self.lo[i].astype(float), self.hi[i].astype(float), piece_lo, piece_hi, v, whole)
                     if self.cartons and getattr(it, "carton", True) else ([], []))
        if not whole:  # a split box: keep what lies in this piece
            clipped = [_shapes.clip_polygon(f, piece_lo, piece_hi) for f in faces]
            keep = [k for k, c in enumerate(clipped) if len(c) >= 3]
            faces = [clipped[k] @ proj for k in keep]
            levels = levels[keep]
            outline = [s for s in (_shapes.clip_segment(a, b, piece_lo, piece_hi) for a, b in outline) if s]
        else:
            faces = faces @ proj
        out = [(_CARTON, _segments_path(np.array(far) @ proj), 1.0)] if far else []
        for level in np.unique(levels):
            group = np.nonzero(levels == level)[0]
            polys = faces[group] if isinstance(faces, np.ndarray) else [faces[k] for k in group]
            out.append((_SHAPE_FACET, _polygons_path(polys), level))
        if len(outline):
            out.append((_OUTLINE, _segments_path(np.array(outline) @ proj), 1.0))
        if near:
            out.append((_CARTON, _segments_path(np.array(near) @ proj), 1.0))
        return out

    def _crate_geometry(self, i, v, proj):
        """A crate drawn open: far walls and edges, its contents, near edges. A
        loading crate: a faint column up to the ceiling and its solid base."""
        crate = self._crate(i)
        lo, hi = self.lo[i].astype(float), self.hi[i].astype(float)
        open_top = crate.type.open_top
        wall, edge = (_OPEN_WALL, _OPEN_EDGE) if open_top else (_CRATE_WALL, _CRATE_EDGE)
        out = []
        for k in range(3):  # walls facing away from the camera
            if abs(v[k]) < 1e-12:
                continue
            at = lo[k] if v[k] > 0 else hi[k]
            a, b = [x for x in range(3) if x != k]
            quad = np.empty((4, 3))
            for n, (ua, ub) in enumerate(((0, 0), (1, 0), (1, 1), (0, 1))):
                quad[n, k], quad[n, a], quad[n, b] = at, (hi if ua else lo)[a], (hi if ub else lo)[b]
            out.append((wall, _polygons_path((quad @ proj)[None]), _SHADE[k], None, None))
        far, near = _carton_edges(lo, hi, lo, hi, v, True)
        out.append((edge, _segments_path(np.array(far) @ proj), 1.0, None, None))
        inside = list(_Scene(_Contents(crate.placed_contents(self.items[i])), v, cartons=False)._geometry(v, proj))
        if open_top:  # the base, below the goods: seen from above it goes first, from below last
            base_hi = hi.copy()
            base_hi[1] = lo[1] + crate.type.base_height
            base = [(_BOX_FACE, _polygons_path((quad @ proj)[None]), _SHADE[axis], None, ("crate base", i))
                    for axis, quad in _faces(lo, base_hi, v)] if base_hi[1] > lo[1] else []
            inside = base + inside if v[1] >= 0 else inside + base
        out += inside
        out.append((edge, _segments_path(np.array(near) @ proj), 1.0, None, None))
        return out

    def _geometry(self, v, proj):
        """[(kind, path, shade, colour source item or None, solid item or None)] per owner piece, in
        drawing order, as (owner, split, primitives) triples (cached: the camera is fixed)."""
        if self._geom is None:
            owners, piece_lo, piece_hi = self.order
            split_items = np.bincount(owners, minlength=len(self.items)) > 1 if len(owners) else np.zeros(0, bool)
            self._geom = []
            for i, plo_i, phi_i in zip(owners, piece_lo, piece_hi):
                it = self.items[i]
                if self._crate(i) is not None:
                    prims = self._crate_geometry(i, v, proj)
                elif _shapes.is_shaped(it):
                    prims = [(k, path, sh, it, it if k == _SHAPE_FACET else None)
                             for k, path, sh in self._shape_paths(i, plo_i, phi_i, not split_items[i], v, proj)]
                else:
                    prims = [(_BOX_FACE, _polygons_path((quad @ proj)[None]), _SHADE[axis], it, it)
                             for axis, quad in _faces(plo_i, phi_i, v)]
                self._geom.append((i, bool(split_items[i]), prims))
        return [p for _, _, prims in self._geom for p in prims]

    def faces(self, v, proj, palette):
        """(owner, paths, colour, faded colour, split, kind) for every drawing
        primitive, in drawing order. Paths are in screen coordinates; owner is
        the loading step (index) of the item, or of the crate a content is in."""
        if getattr(self, "_palette", None) is not palette:
            from matplotlib.colors import to_rgb

            self._geometry(v, proj)
            owner, paths, rgb, split, kind, solids = [], [], [], [], [], []
            cache = {}
            for i, is_split, prims in self._geom:
                for k, path, shade, src, solid in prims:
                    if src is None:
                        base = _CRATE_RGB
                    else:
                        key = id(src)
                        if key not in cache:
                            cache[key] = np.array(to_rgb(palette.color(src)))
                        base = cache[key]
                    owner.append(i)
                    paths.append(path)
                    rgb.append(np.clip(base * shade, 0, 1))
                    split.append(is_split)
                    kind.append(k)
                    solids.append(solid)
            colors = np.array(rgb).reshape(-1, 3)
            self._palette = palette
            self._faces = (np.array(owner, dtype=np.int64), paths, colors, colors * 0.25 + 0.75,
                           np.array(split, dtype=bool), np.array(kind, dtype=np.int64))
            # The item each filled primitive shows: None for lines and crate walls, ("crate base", i)
            # for the base of loading crate i.
            self.solids = solids
        return self._faces


class _Contents:
    """A crate's contents in container coordinates, as a bin-like list for a sub-scene."""

    def __init__(self, items):
        self._items = items

    def get_items(self):
        return self._items


def _palette_items(items, crates=None):
    """Items that get a colour: crates stand for their contents."""
    out = []
    for it in items:
        k = getattr(it, "crate_index", -1)
        if crates is not None and k >= 0:
            out += list(crates[k].contents)
        else:
            out.append(it)
    return out


def _draw_bin(ax, scene, v, proj, palette, *, offset=(0.0, 0.0), upto=None, highlight=0, labels="auto",
              label_limit=80, show_container=True, zorder=0):
    """Draws one bin translated by `offset` (screen units). Returns nothing."""
    from matplotlib.collections import LineCollection, PathCollection, PolyCollection
    from matplotlib.transforms import Affine2D

    off = np.asarray(offset, dtype=float)
    count = len(scene.items) if upto is None else max(0, min(upto, len(scene.items)))
    first_new = count - highlight if highlight else 0
    size = _bin_size(scene.bin)
    corners = _corners(size)

    if show_container:  # far walls behind the cargo
        walls, wall_colors = [], []
        for k in range(3):
            if abs(v[k]) < 1e-12:
                continue
            at = 0.0 if v[k] > 0 else size[k]
            quad = corners[corners[:, k] == at]
            a, b = [x for x in range(3) if x != k]
            quad = quad[np.lexsort((quad[:, b], quad[:, a]))][[0, 1, 3, 2]]
            walls.append(quad @ proj + off)
            wall_colors.append((0.93, 0.93, 0.95) if k != 1 else (0.86, 0.86, 0.88))
        ax.add_collection(PolyCollection(walls, facecolors=wall_colors, edgecolors=(0.6, 0.6, 0.65),
                                         linewidths=0.8, zorder=zorder + 1))

    face_owner, paths, colors, faded, split, kind = scene.faces(v, proj, palette)
    shown = face_owner < count
    kind = kind[shown]
    fill = np.where((face_owner < first_new)[:, None], faded, colors)[shown]
    alpha = np.ones(len(kind))
    for wall_kind, wall_alpha in _WALL_ALPHA.items():
        alpha[kind == wall_kind] = wall_alpha
    fill = np.hstack([fill, alpha[:, None]])
    # Box faces: dark edges, except the seams of split boxes; shape facets: no edges
    # (see _LINE_WIDTHS); outlines and carton edges: lines only.
    seamless = split[shown] & (kind == _BOX_FACE)
    edge_colors = np.where(seamless[:, None], fill, _EDGE_COLOR)
    edge_colors[kind == _OUTLINE] = _OUTLINE_COLOR
    edge_colors[kind == _CARTON] = _CARTON_COLOR
    edge_colors[kind == _CRATE_EDGE] = _CRATE_EDGE_COLOR
    edge_colors[kind == _OPEN_EDGE] = _OPEN_EDGE_COLOR
    fill[np.isin(kind, _LINES)] = 0.0  # transparent
    ax.add_collection(PathCollection([paths[j] for j in np.nonzero(shown)[0]], facecolors=fill,
                                     edgecolors=edge_colors, linewidths=_LINE_WIDTHS[kind],
                                     antialiaseds=kind != _SHAPE_FACET,
                                     transform=Affine2D().translate(*off) + ax.transData, zorder=zorder + 2),
                      autolim=False)

    if show_container:
        # Near edges only (far edges are the wall outlines drawn behind the cargo).
        far = [(k, 0.0 if v[k] > 0 else size[k]) for k in range(3) if abs(v[k]) >= 1e-12]
        edges = []
        for p in corners:
            for k in range(3):
                if p[k] == 0:
                    q = p.copy()
                    q[k] = size[k]
                    if not any(p[a] == at and q[a] == at for a, at in far):
                        edges.append([p @ proj + off, q @ proj + off])
        ax.add_collection(LineCollection(edges, colors=(0.35, 0.35, 0.4, 0.6), linewidths=0.7,
                                         linestyles="--", zorder=zorder + 3))
        # Door and back ends, outside the outline (never over the cargo).
        for label, z in (("DOOR", size[2]), ("BACK", 0.0)):
            ends = np.array([[x, y, z] for x in (0, size[0]) for y in (0, size[1])]) @ proj
            outward = ends.mean(axis=0) - (corners @ proj).mean(axis=0)
            outward = outward / (np.linalg.norm(outward) or 1.0)
            edge = ends[np.argmax(ends @ outward)] + off
            ax.annotate(label, edge, xytext=tuple(outward * 14), textcoords="offset points", ha="center",
                        va="center", fontsize=7, color="#444", zorder=zorder + 4, fontweight="bold")

    show_labels = labels is True or (labels == "auto" and 0 < count <= label_limit)
    if show_labels:
        ids = np.arange(first_new, count) if highlight else np.arange(count)
        lo, hi = scene.lo[:count], scene.hi[:count]
        anchors = [scene.anchor(i, v) for i in ids]
        if anchors:
            hidden = _occluded(np.array(anchors), lo, hi, v, list(ids))
            for p, i, h in zip(anchors, ids, hidden):
                if not h:
                    x, y = p @ proj + off
                    ax.text(x, y, str(i + 1), ha="center", va="center", fontsize=7, zorder=zorder + 5,
                            color="#111", fontweight="bold")


def _finish_axes(ax, box, pad_frac=0.04):
    xmin, xmax, ymin, ymax = box
    pad = pad_frac * max(xmax - xmin, ymax - ymin)
    ax.set_xlim(xmin - pad, xmax + pad)
    ax.set_ylim(ymin - pad * 2, ymax + pad)
    ax.set_aspect("equal")
    ax.axis("off")


def _legend(ax, palette, below=False, max_entries=16):
    from matplotlib.patches import Patch

    entries = list(palette.legend().items())[:max_entries]
    if not entries:
        return
    handles = [Patch(facecolor=c, edgecolor="#333", label=l) for l, c in entries]
    if below:  # fleet views: under the drawing, never over a container caption
        ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, 0.0), fontsize=7, frameon=False,
                  ncol=min(4, len(handles)))
    else:
        ax.legend(handles=handles, loc="upper left", fontsize=7, frameon=False, bbox_to_anchor=(0.0, 1.0))


def _bin_caption(bin_, items):
    vol = sum(it.get_volume() for it in items)
    weight = sum(it.weight for it in items)
    parts = [f"{bin_.get_name()}: {len(items)} items", f"{vol / max(1.0, float(np.prod(_bin_size(bin_)))):.0%} volume"]
    if weight:
        parts.append(f"{weight:,.0f} weight")
    if bin_.cost:
        parts.append(f"cost {bin_.cost:,.0f}")
    return ", ".join(parts)


def render_bin(bin_, ax=None, *, upto: int | None = None, highlight: int = 0, view=DEFAULT_VIEW,
               color_by: str = "auto", palette: Palette | None = None, labels="auto", label_limit: int = 80,
               show_container: bool = True, legend: bool = True, title: str | bool = True, cartons: bool = True):
    """Draws one packed bin.

    upto:       draw only the first ``upto`` items of the loading sequence.
    highlight:  draw the last ``highlight`` of those in colour, earlier ones faded.
    view:       (azimuth, elevation) in degrees, see :func:`camera`.
    color_by:   "auto" (item colours if set, else item types), "color", "type",
                "group" or "priority"; or pass a shared :class:`Palette`.
    labels:     write loading-step numbers on the items (True / False / "auto":
                when at most ``label_limit`` items are drawn). Hidden labels are skipped.
    cartons:    outline the thin carton around shaped items (spheres, cones, ...).
    Returns the matplotlib Axes.
    """
    plt = _plt()
    if ax is None:
        _, ax = plt.subplots(figsize=(11, 6.5))
    v, right, up = camera(view)
    proj = np.stack([right, up], axis=1)
    scene = _Scene(bin_, v, cartons)
    palette = palette or Palette(_palette_items(scene.items, scene.crates), color_by)
    _draw_bin(ax, scene, v, proj, palette, upto=upto, highlight=highlight, labels=labels,
              label_limit=label_limit, show_container=show_container)
    _finish_axes(ax, _extent(bin_, proj))
    if title:
        shown = scene.items if upto is None else scene.items[:upto]
        ax.set_title(_bin_caption(bin_, shown) if title is True else title, fontsize=10)
    if legend:
        _legend(ax, palette)
    return ax


# --------------------------------------------------------------------- fleet --

def _used_bins(packer):
    used = [b for b in packer.get_bins() if b.get_items()]
    if not used:
        raise ValueError("no bin contains items - call pack() first")
    return used


def _fleet_layout(bins, proj, cols=None):
    """Offsets for drawing every bin at one scale: rows filled left to right
    ("shelves"), each row as tall as its tallest bin plus room for captions.
    With `cols`, rows hold exactly that many bins. Returns (offsets, bounding box)."""
    boxes = [_extent(b, proj) for b in bins]
    widths = [b[1] - b[0] for b in boxes]
    heights = [b[3] - b[2] for b in boxes]
    gap = 0.08 * max(widths)
    caption = 0.22 * max(heights)
    if cols:
        rows = [list(range(k, min(k + cols, len(bins)))) for k in range(0, len(bins), cols)]
    else:
        limit = max(max(widths), 1.5 * sum(widths) / np.ceil(np.sqrt(len(bins))))
        rows, row, width = [], [], 0.0
        for k, w in enumerate(widths):
            if row and width + gap + w > limit:
                rows.append(row)
                row, width = [], 0.0
            width += (gap if row else 0.0) + w
            row.append(k)
        rows.append(row)
    offsets = [None] * len(bins)
    top, right = 0.0, 0.0
    for row in rows:
        row_h = max(heights[k] for k in row) + caption
        bottom = top - row_h
        x = 0.0
        for k in row:
            xmin, _, ymin, _ = boxes[k]
            offsets[k] = (x - xmin, bottom - ymin)
            x += widths[k] + gap
        right = max(right, x - gap)
        top = bottom - gap
    return offsets, (0.0, right, top + gap, 0.0)


def render_fleet(packer, ax=None, *, view=DEFAULT_VIEW, color_by: str = "auto", cols: int | None = None,
                 progress: dict | None = None, labels=False, legend: bool = True, title: str | bool = True,
                 cartons: bool = True, _scenes: dict | None = None, _palette: Palette | None = None):
    """All bins that received items, side by side at the same scale (a tempo
    looks small next to a 40ft container), with name, fill and cost.

    progress: optional {bin_index: (upto, highlight)} to draw loading states
    (used by the animation). Returns the Axes.
    """
    plt = _plt()
    bins = [_scenes[k].bin for k in sorted(_scenes)] if _scenes else _used_bins(packer)
    v, right, up = camera(view)
    proj = np.stack([right, up], axis=1)
    if ax is None:
        _, ax = plt.subplots(figsize=_fleet_figsize(bins, proj, cols))
    palette = _palette or Palette(_palette_items(packer.get_items(), getattr(packer, "crates", None)), color_by)
    offsets, box = _fleet_layout(bins, proj, cols)
    for k, (bin_, off) in enumerate(zip(bins, offsets)):
        scene = (_scenes or {}).get(k) or _Scene(bin_, v, cartons)
        upto, highlight = (progress or {}).get(k, (None, 0))
        _draw_bin(ax, scene, v, proj, palette, offset=off, upto=upto, highlight=highlight, labels=labels)
        xmin, xmax, ymin, ymax = _extent(bin_, proj)
        shown = scene.items if upto is None else scene.items[:upto]
        ax.text(off[0] + (xmin + xmax) / 2, off[1] + ymax, _bin_caption(bin_, shown), ha="center", va="bottom",
                fontsize=8)
    _finish_axes(ax, box, pad_frac=0.02)
    if title:
        if title is True:
            unfit = len(packer.get_unfit_items())
            title = f"{len(bins)} container{'s' if len(bins) > 1 else ''}"
            cost = packer.get_total_cost()
            if cost:
                title += f", total cost {cost:,.0f}"
            if unfit:
                title += f", {unfit} item(s) not loaded"
        ax.set_title(title, fontsize=11)
    if legend:
        _legend(ax, palette, below=True)
    return ax


def _fleet_figsize(bins, proj, cols=None, width=13.0):
    _, box = _fleet_layout(bins, proj, cols)
    aspect = (box[3] - box[2]) / max(1e-9, box[1] - box[0])
    return (width, min(16.0, max(3.5, width * aspect + 1.2)))


def render_packer(packer, view=DEFAULT_VIEW, color_by: str = "auto", cols: int | None = None, figsize=None,
                  cartons: bool = True):
    """Figure with every used bin at a common scale (see :func:`render_fleet`)."""
    plt = _plt()
    bins = _used_bins(packer)
    _, right, up = camera(view)
    fig, ax = plt.subplots(figsize=figsize or _fleet_figsize(bins, np.stack([right, up], axis=1), cols))
    render_fleet(packer, ax, view=view, color_by=color_by, cols=cols, cartons=cartons)
    fig.tight_layout()
    return fig


def render_loading_steps(target, panels: int = 6, cols: int = 3, view=DEFAULT_VIEW, color_by: str = "auto",
                         figsize=None, cartons: bool = True):
    """Snapshots of the loading sequence, each chunk of new steps in colour.

    For a Bin: a grid of ``panels`` snapshots. For a Packer: one row per used
    bin with ``panels`` snapshots each, all at the same scale. Returns the Figure.
    """
    plt = _plt()
    is_packer = hasattr(target, "get_bins")
    bins = _used_bins(target) if is_packer else [target]
    palette = Palette(_palette_items(target.get_items(), getattr(target, "crates", None)), color_by)
    v, right, up = camera(view)
    proj = np.stack([right, up], axis=1)
    if is_packer:
        grid_rows, grid_cols = len(bins), panels
    else:
        n = len(target.get_items())
        panels = max(1, min(panels, n)) if n else 1
        grid_rows, grid_cols = -(-panels // cols), cols
    fig, axes = plt.subplots(grid_rows, grid_cols, figsize=figsize or (5.0 * grid_cols, 3.1 * grid_rows),
                             squeeze=False)
    # One scale for every panel: the largest bin's extent.
    extents = [_extent(b, proj) for b in bins]
    span_w = max(e[1] - e[0] for e in extents)
    span_h = max(e[3] - e[2] for e in extents)
    for r, bin_ in enumerate(bins):
        scene = _Scene(bin_, v, cartons)
        n = len(scene.items)
        count = panels if is_packer else panels
        cuts = np.linspace(0, n, count + 1).round().astype(int)
        for p in range(count):
            ax = axes[r, p] if is_packer else axes.flat[p]
            start, end = cuts[p], cuts[p + 1]
            _draw_bin(ax, scene, v, proj, palette, upto=end, highlight=end - start, labels="auto", label_limit=40)
            xmin, xmax, ymin, ymax = extents[r]
            cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
            _finish_axes(ax, (cx - span_w / 2, cx + span_w / 2, cy - span_h / 2, cy + span_h / 2))
            name = f"{bin_.get_name()}: " if is_packer else ""
            ax.set_title(f"{name}steps {start + 1}-{end}" if end > start else f"{name}empty", fontsize=9)
    if not is_packer:
        for ax in list(axes.flat)[panels:]:
            ax.axis("off")
    label = "loading sequence" if not is_packer else f"loading sequence of {len(bins)} bins"
    fig.suptitle(f"{bins[0].get_name() if not is_packer else 'Fleet'}: {label}", fontsize=12)
    fig.tight_layout()
    return fig


def _reset(ax):
    """Removes what a frame drew (much cheaper than ax.clear())."""
    for artist in list(ax.collections) + list(ax.texts) + list(ax.patches):
        artist.remove()
    if ax.get_legend() is not None:
        ax.get_legend().remove()


def animate_loading(target, path: str, frames: int = 60, fps: int = 6, view=DEFAULT_VIEW,
                    color_by: str = "auto", figsize=None, dpi: int = 80, cartons: bool = True):
    """Saves an animation (GIF via Pillow, or any format matplotlib supports) of
    the loading sequence, the newest items in colour.

    For a Packer the whole fleet is shown at a common scale and the bins are
    loaded one after another (frames are shared out by item count).
    """
    plt = _plt()
    from matplotlib.animation import FuncAnimation

    is_packer = hasattr(target, "get_bins")
    v, _, _ = camera(view)
    if is_packer:
        bins = _used_bins(target)
        scenes = {k: _Scene(b, v, cartons) for k, b in enumerate(bins)}
        palette = Palette(_palette_items(target.get_items(), getattr(target, "crates", None)), color_by)
        counts = [len(s.items) for s in scenes.values()]
        total = sum(counts)
        # (bin, upto) for every frame, frames shared out by item count.
        steps = []
        for k, n in enumerate(counts):
            share = max(1, round(frames * n / max(1, total)))
            for upto in np.unique(np.linspace(0, n, share + 1).round().astype(int))[1:]:
                steps.append((k, int(upto)))
        cols = None
        _, right, up = camera(view)
        fig, ax = plt.subplots(figsize=figsize or _fleet_figsize(bins, np.stack([right, up], axis=1)))

        def draw(f):
            _reset(ax)
            k, upto = steps[f]
            prev = steps[f - 1][1] if f > 0 and steps[f - 1][0] == k else 0
            progress = {j: ((None, 0) if j < k else (upto, upto - prev) if j == k else (0, 0))
                        for j in range(len(bins))}
            render_fleet(target, ax, view=view, color_by=color_by, cols=cols, progress=progress, _scenes=scenes,
                         _palette=palette, title=f"Loading {bins[k].get_name()}: step {upto} of {counts[k]}")
            return []

        n_frames = len(steps)
    else:
        scene = _Scene(target, v, cartons)
        n = len(scene.items)
        cuts = np.unique(np.linspace(0, n, max(2, min(frames, n) + 1)).round().astype(int))
        palette = Palette(_palette_items(scene.items, scene.crates), color_by)
        fig, ax = plt.subplots(figsize=figsize or (11, 6.5))
        _, right, up = camera(view)
        proj = np.stack([right, up], axis=1)

        def draw(f):
            _reset(ax)
            prev = cuts[f - 1] if f > 0 else 0
            _draw_bin(ax, scene, v, proj, palette, upto=cuts[f], highlight=cuts[f] - prev, labels=False)
            _finish_axes(ax, _extent(target, proj))
            ax.set_title(f"{target.get_name()}: step {cuts[f]} of {n}", fontsize=10)
            return []

        n_frames = len(cuts)

    anim = FuncAnimation(fig, draw, frames=n_frames, blit=False)
    anim.save(path, fps=fps, dpi=dpi, writer="pillow" if str(path).lower().endswith(".gif") else None)
    plt.close(fig)
    return path
