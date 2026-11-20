"""Geometry of shaped items (sphere, pyramid, cone, cylinder) for drawing.

The packer treats every item as its w x h x d box: shaped goods ship in a thin
carton of that size. These helpers describe the real shape inside that box so
the renderer can draw it:

* the shape is inscribed in the item's box, in the item's own axes (w, h, d):
  a sphere (an ellipsoid when the sides differ), a cylinder or cone standing
  on its w x d base (elliptical when w != d) with its axis along h, and a
  pyramid on its rectangular w x d base with the apex on top;
* the item's rotation maps these axes to the placed x, y, z, so a cylinder
  rotated with its h along x lies on its side. Cones and pyramids keep their
  apex towards the positive end of the axis their height maps to.

Every shape is convex and lies inside its box, which is what lets the
renderer draw it in the box's slot of the back-to-front order.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

import pybinding as _core

SEGMENTS = 32        # around the axis of cylinders and cones, around the equator of spheres
SPHERE_RINGS = 14    # from pole to pole
_SHARP_DEG = 35.0    # edges between faces bent more than this are drawn (rims, pyramid ridges)

# For each rotation: which item axis (0 = w, 1 = h, 2 = d) lies along placed x, y and z.
# Matches rotatedDimensions() in include/item.h.
_AXES = {
    _core.RotationType.whd: (0, 1, 2),
    _core.RotationType.hwd: (1, 0, 2),
    _core.RotationType.hdw: (1, 2, 0),
    _core.RotationType.dhw: (2, 1, 0),
    _core.RotationType.dwh: (2, 0, 1),
    _core.RotationType.wdh: (0, 2, 1),
}


def is_shaped(item) -> bool:
    """True for items drawn as something other than their box."""
    return item.shape != _core.Shape.BOX


def shape_name(item) -> str:
    """"box", "sphere", "pyramid", "cone" or "cylinder"."""
    return item.shape.name.lower()


@dataclass(frozen=True)
class Mesh:
    """A closed convex polyhedron in the unit box [0, 1]^3 of the item's axes (w, h, d).

    faces: (f, 4) vertex indices; triangles repeat their last vertex.
    normals: (f, 3) outward unit normals. edges: (e, 2) vertex indices,
    edge_faces: (e, 2) the two faces sharing each edge, sharp: (e,) bool.
    """

    vertices: np.ndarray
    faces: np.ndarray
    normals: np.ndarray
    edges: np.ndarray
    edge_faces: np.ndarray
    sharp: np.ndarray


def _ring(y, radius, n=SEGMENTS):
    """n points on a horizontal circle of the unit box, centred on its axis."""
    a = 2 * np.pi * np.arange(n) / n
    return np.stack([0.5 + radius * np.cos(a), np.full(n, y), 0.5 + radius * np.sin(a)], axis=1)


def _fan(centre, ring):
    n = len(ring)
    return [(centre, ring[i], ring[(i + 1) % n], ring[(i + 1) % n]) for i in range(n)]


def _band(lower, upper):
    n = len(lower)
    return [(lower[i], lower[(i + 1) % n], upper[(i + 1) % n], upper[i]) for i in range(n)]


def _polyhedron(kind):
    """(vertices, faces) of a unit shape; faces are 4 indices, triangles repeat a vertex."""
    n = SEGMENTS
    if kind == _core.Shape.PYRAMID:
        verts = np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1], [0.5, 1, 0.5]], dtype=float)
        faces = [(0, 1, 2, 3)] + [(i, (i + 1) % 4, 4, 4) for i in range(4)]
        return verts, faces
    if kind == _core.Shape.CYLINDER:
        verts = np.vstack([_ring(0.0, 0.5), _ring(1.0, 0.5), [[0.5, 0, 0.5], [0.5, 1, 0.5]]])
        bottom, top = list(range(n)), list(range(n, 2 * n))
        return verts, _band(bottom, top) + _fan(2 * n, bottom) + _fan(2 * n + 1, top)
    if kind == _core.Shape.CONE:
        verts = np.vstack([_ring(0.0, 0.5), [[0.5, 0, 0.5], [0.5, 1, 0.5]]])
        ring = list(range(n))
        sides = [(ring[i], ring[(i + 1) % n], n + 1, n + 1) for i in range(n)]
        return verts, sides + _fan(n, ring)
    if kind == _core.Shape.SPHERE:
        polar = np.pi * np.arange(1, SPHERE_RINGS) / SPHERE_RINGS
        rings = [_ring(0.5 - 0.5 * np.cos(p), 0.5 * np.sin(p)) for p in polar]
        verts = np.vstack(rings + [[[0.5, 0, 0.5], [0.5, 1, 0.5]]])
        idx = [list(range(k * n, (k + 1) * n)) for k in range(len(rings))]
        south, north = len(verts) - 2, len(verts) - 1
        faces = _fan(south, idx[0]) + _fan(north, idx[-1])
        for lower, upper in zip(idx, idx[1:]):
            faces += _band(lower, upper)
        return verts, faces
    raise ValueError(f"no mesh for shape {kind}")


@lru_cache(maxsize=None)
def unit_mesh(kind) -> Mesh:
    """The mesh of a shape in the unit box (cached; the same for every item)."""
    verts, faces = _polyhedron(kind)
    faces = np.array(faces, dtype=np.int64)
    inside = np.array([0.5, 0.3, 0.5])  # a point inside every shape
    normals = np.empty((len(faces), 3))
    for f, idx in enumerate(faces):
        p = verts[idx]
        n = np.cross(p[1] - p[0], p[2] - p[0])
        if np.linalg.norm(n) < 1e-12:  # first corner is degenerate (never for these meshes)
            n = np.cross(p[2] - p[1], p[3] - p[1])
        n /= np.linalg.norm(n)
        normals[f] = n if n @ (p.mean(axis=0) - inside) > 0 else -n
    # Edge -> the two faces that share it (closed meshes: exactly two).
    owners: dict = {}
    for f, idx in enumerate(faces):
        ring = list(dict.fromkeys(idx.tolist()))  # drop the repeated triangle corner
        for a, b in zip(ring, ring[1:] + ring[:1]):
            owners.setdefault((min(a, b), max(a, b)), []).append(f)
    assert all(len(fs) == 2 for fs in owners.values()), "mesh is not closed"
    edges = np.array(list(owners), dtype=np.int64)
    edge_faces = np.array(list(owners.values()), dtype=np.int64)
    cos_sharp = np.cos(np.radians(_SHARP_DEG))
    sharp = np.einsum("ij,ij->i", normals[edge_faces[:, 0]], normals[edge_faces[:, 1]]) < cos_sharp
    return Mesh(verts, faces, normals, edges, edge_faces, sharp)


@dataclass
class PlacedMesh:
    """A shape in bin coordinates: vertices (n, 3), unit outward normals (f, 3) and its mesh.

    axis: placed axis (0, 1, 2) of the item's height; apex: +1 or -1, the
    direction along it of a cone's tip / pyramid's apex (-1 = inverted);
    lo, size: the box it fills.
    """

    vertices: np.ndarray
    normals: np.ndarray
    mesh: Mesh
    kind: object = None
    axis: int = 1
    apex: int = 1
    lo: np.ndarray = None
    size: np.ndarray = None


def _inverted(item) -> bool:
    """Bulk loads stand every other cone / pyramid on its tip (see binpack.bulk)."""
    return bool(getattr(item, "inverted", False))


def place(item) -> PlacedMesh:
    """The item's shape where the packer put it (position, size, rotation and inversion)."""
    mesh = unit_mesh(item.shape)
    axes = _AXES[item.get_rotation_type()]
    size = np.array([item.width, item.height, item.depth], dtype=float)  # item axes (w, h, d)
    pos = np.array(item.get_position(), dtype=float)
    unit, unit_normals = mesh.vertices, mesh.normals
    if _inverted(item):  # upside down along the item's height
        unit = unit * [1, -1, 1] + [0, 1, 0]
        unit_normals = unit_normals * [1, -1, 1]
    scaled = unit * size
    # Normals transform with the inverse transpose of the scaling (and the same axis permutation).
    normals = (unit_normals / np.where(size > 0, size, 1.0))[:, axes]
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-300)
    return PlacedMesh(scaled[:, axes] + pos, normals, mesh, item.shape, axes.index(1),
                      -1 if _inverted(item) else 1, pos, size[list(axes)])


def visible_parts(placed: PlacedMesh, v, eps: float = 1e-9):
    """What the camera (looking along -v) sees of a convex shape.

    Returns ``(faces, normals, outline)``: the front-facing faces as (f, 4, 3)
    corner arrays with their normals, and the edges to draw as (e, 2, 3)
    segments: the silhouette and the sharp edges (rims, ridges) on the visible side.
    """
    mesh = placed.mesh
    front = placed.normals @ np.asarray(v, dtype=float) > eps
    faces = placed.vertices[mesh.faces[front]]
    ef = front[mesh.edge_faces]
    draw = (ef[:, 0] != ef[:, 1]) | (mesh.sharp & ef.any(axis=1))
    outline = placed.vertices[mesh.edges[draw]]
    return faces, placed.normals[front], outline


def inside_unit(kind, u) -> np.ndarray:
    """Is each point u (m, 3) of the unit box (item axes w, h, d) inside the shape?"""
    x, y, z = 2 * u[:, 0] - 1, u[:, 1], 2 * u[:, 2] - 1  # x, z in [-1, 1] around the axis; y in [0, 1]
    in_box = (np.abs(x) <= 1) & (y >= 0) & (y <= 1) & (np.abs(z) <= 1)
    if kind == _core.Shape.SPHERE:
        return x * x + (2 * y - 1) ** 2 + z * z <= 1
    if kind == _core.Shape.CYLINDER:
        return in_box & (x * x + z * z <= 1)
    if kind == _core.Shape.CONE:
        return in_box & (x * x + z * z <= (1 - y) ** 2)
    if kind == _core.Shape.PYRAMID:
        return in_box & (np.abs(x) <= 1 - y) & (np.abs(z) <= 1 - y)
    return in_box


def inside(item, points) -> np.ndarray:
    """Is each point (m, 3) in bin coordinates inside the item's real shape?"""
    axes = _AXES[item.get_rotation_type()]
    size = np.array([item.width, item.height, item.depth], dtype=float)
    inverse = np.argsort(axes)  # placed axis of each item axis
    rel = (np.asarray(points, dtype=float).reshape(-1, 3) - np.array(item.get_position(), dtype=float))
    unit = rel[:, inverse] / np.where(size > 0, size, 1.0)
    if _inverted(item):
        unit[:, 1] = 1 - unit[:, 1]
    return inside_unit(item.shape, unit)


def front_point(item, v, iterations: int = 40) -> np.ndarray:
    """Point of the shape's surface the camera sees in the middle of the item's box.

    The box centre is inside every shape, and the shapes are convex, so the
    surface point is found by bisection along the view ray.
    """
    lo = np.array(item.get_position(), dtype=float)
    dims = np.array(item.get_dimension(), dtype=float)
    centre = lo + dims / 2
    v = np.asarray(v, dtype=float)
    with np.errstate(divide="ignore"):
        t_max = float(np.min(np.where(np.abs(v) > 1e-12, dims / 2 / np.abs(v), np.inf)))
    a, b = 0.0, t_max
    for _ in range(iterations):
        mid = (a + b) / 2
        a, b = (mid, b) if inside(item, centre + mid * v)[0] else (a, mid)
    return centre + a * v


def _base_reach(placed: PlacedMesh, e) -> float:
    """How far the base of a cone / pyramid reaches from its axis in direction e (perpendicular to the axis)."""
    half = placed.size / 2
    others = [k for k in range(3) if k != placed.axis]
    a, b = half[others[0]] * e[others[0]], half[others[1]] * e[others[1]]
    return float(abs(a) + abs(b)) if placed.kind == _core.Shape.PYRAMID else float(np.hypot(a, b))


def in_front(a: PlacedMesh, b: PlacedMesh, v) -> int:
    """+1 if b is in front of a seen along -v, -1 if a is in front of b, 0 if
    neither hides the other. For disjoint shapes whose boxes overlap (bulk loads).

    Finds a plane separating the two meshes among a few candidates: the
    centre-to-centre direction, the same perpendicular to the shapes' axis
    (side by side), the axis itself (stacked) and the slanted side planes of
    cones / pyramids (tip-up next to tip-down). The shape on the side the
    camera looks from is in front.
    """
    v = np.asarray(v, dtype=float)
    ca, cb = a.lo + a.size / 2, b.lo + b.size / 2
    d = cb - ca
    u = np.zeros(3)
    u[a.axis] = 1.0
    perp = d - (d @ u) * u
    candidates = [d, perp, u, np.eye(3)[0], np.eye(3)[2]]
    if a.kind in (_core.Shape.CONE, _core.Shape.PYRAMID) and np.linalg.norm(perp) > 0:
        e = perp / np.linalg.norm(perp)
        height, reach = a.size[a.axis], _base_reach(a, e)
        candidates += [height * e + reach * u, height * e - reach * u]
    tol = 1e-6 * float(max(a.size.max(), b.size.max(), 1.0))
    for n in candidates:
        norm = np.linalg.norm(n)
        if norm < 1e-12:
            continue
        n = n / norm
        pa, pb = a.vertices @ n, b.vertices @ n
        if pa.max() <= pb.min() + tol:
            side = 1  # b on the +n side
        elif pb.max() <= pa.min() + tol:
            side = -1
        else:
            continue
        facing = n @ v
        if abs(facing) < 1e-9:
            return 0  # separated sideways on screen: neither hides the other
        return side if facing > 0 else -side
    return 1 if d @ v > 0 else -1  # no plane found (not expected): nearer centre in front


# ------------------------------------------------------------------ clipping --

def clip_polygon(points: np.ndarray, lo, hi) -> np.ndarray:
    """Sutherland-Hodgman clip of a planar 3D polygon to the box [lo, hi]; (k, 3), maybe empty."""
    poly = [p for p in points]
    for k in range(3):
        for bound, keep in ((lo[k], lambda c, b: c >= b), (hi[k], lambda c, b: c <= b)):
            if not poly:
                return np.zeros((0, 3))
            out = []
            for i, cur in enumerate(poly):
                prev = poly[i - 1]
                cin, pin = keep(cur[k], bound), keep(prev[k], bound)
                if cin != pin:
                    t = (bound - prev[k]) / (cur[k] - prev[k])
                    out.append(prev + t * (cur - prev))
                if cin:
                    out.append(cur)
            poly = out
    return np.array(poly) if poly else np.zeros((0, 3))


def clip_segment(a: np.ndarray, b: np.ndarray, lo, hi):
    """Liang-Barsky clip of segment a-b to the box [lo, hi]; (a', b') or None."""
    t0, t1 = 0.0, 1.0
    d = b - a
    for k in range(3):
        if abs(d[k]) < 1e-12:
            if a[k] < lo[k] or a[k] > hi[k]:
                return None
            continue
        ta, tb = (lo[k] - a[k]) / d[k], (hi[k] - a[k]) / d[k]
        t0, t1 = max(t0, min(ta, tb)), min(t1, max(ta, tb))
        if t0 >= t1:
            return None
    return a + t0 * d, a + t1 * d


# --------------------------------------------------------------- validation --

def _frame(item):
    """(centre, half sizes on the placed axes, axis of the height, apex direction +1 / -1)."""
    lo = np.array(item.get_position(), dtype=float)
    half = np.array(item.get_dimension(), dtype=float) / 2
    axis = _AXES[item.get_rotation_type()].index(1)
    return lo + half, half, axis, (-1 if _inverted(item) else 1)


def support(item, n) -> float:
    """max of x . n over the item's real shape (exact, for any direction n)."""
    n = np.asarray(n, dtype=float)
    centre, half, axis, apex = _frame(item)
    others = [k for k in range(3) if k != axis]
    round_reach = float(np.hypot(half[others[0]] * n[others[0]], half[others[1]] * n[others[1]]))
    kind = item.shape
    if kind == _core.Shape.SPHERE:
        return float(centre @ n + np.sqrt(np.sum((half * n) ** 2)))
    if kind == _core.Shape.CYLINDER:
        return float(centre @ n + half[axis] * abs(n[axis]) + round_reach)
    if kind in (_core.Shape.CONE, _core.Shape.PYRAMID):
        tip = centre @ n + apex * half[axis] * n[axis]
        base = centre @ n - apex * half[axis] * n[axis]
        base += round_reach if kind == _core.Shape.CONE else float(np.sum(np.abs(half[others] * n[others])))
        return float(max(tip, base))
    return float(centre @ n + np.sum(np.abs(half * n)))  # box


def shapes_overlap(a, b, tol: float = 1e-6) -> bool:
    """Do the real shapes of two items share volume? Looks for a separating
    plane among the directions that separate neighbours of the packing
    patterns (centre to centre, side by side, stacked, sloping faces of tip-up
    / tip-down cones and pyramids), also in the stretched space of non-round
    shapes. Exact supports, so touching shapes are fine. A True answer means
    no plane was found: for these convex shapes that is an overlap."""
    ca, ha, axa, _ = _frame(a)
    cb, hb, axb, _ = _frame(b)
    d = cb - ca
    scale = max(float(ha.max()), float(hb.max()), 1.0)
    candidates = [d, np.eye(3)[0], np.eye(3)[1], np.eye(3)[2]]
    for half, axis, kind in ((ha, axa, a.shape), (hb, axb, b.shape)):
        u = np.eye(3)[axis]
        for stretch in (np.ones(3), half):  # real space, and the space where the shape is round
            ds = d / stretch
            perp = ds - (ds @ u) * u
            local = [ds, perp]
            if kind in (_core.Shape.CONE, _core.Shape.PYRAMID) and np.linalg.norm(perp) > 0:
                e = perp / np.linalg.norm(perp)
                h = half[axis] / stretch[axis]
                others = [k for k in range(3) if k != axis]
                r = half[others] / stretch[others] * e[others]
                reach = float(np.sum(np.abs(r))) if kind == _core.Shape.PYRAMID else float(np.hypot(*r))
                local += [2 * h * e + reach * u, 2 * h * e - reach * u]
            candidates += [n / stretch for n in local]  # back to real space (inverse transpose)
    for n in candidates:
        norm = np.linalg.norm(n)
        if norm < 1e-12:
            continue
        n = n / norm
        if support(a, n) <= -support(b, -n) + tol * scale or support(b, n) <= -support(a, -n) + tol * scale:
            return False
    return True


def overlapping_pairs(items, tol: float = 1e-6) -> list[tuple[int, int]]:
    """Index pairs of items whose real shapes overlap (only pairs whose boxes intersect are tested)."""
    if len(items) < 2:
        return []
    lo = np.array([it.get_position() for it in items], dtype=float)
    hi = lo + np.array([it.get_dimension() for it in items], dtype=float)
    eps = tol * max(1.0, float(np.abs(hi).max()))
    out, seen = [], {}

    def kind(it):
        return (it.shape, it.width, it.height, it.depth, it.get_rotation_type(), _inverted(it))

    for i in range(len(items)):
        near = np.nonzero(np.all((lo[i] < hi - eps) & (lo < hi[i] - eps), axis=1))[0]
        for j in near[near > i]:
            # Packing patterns repeat: the answer only depends on the two kinds and their offset.
            key = (kind(items[i]), kind(items[j]), tuple(np.round(lo[j] - lo[i], 6)))
            if key not in seen:
                seen[key] = shapes_overlap(items[i], items[j], tol)
            if seen[key]:
                out.append((i, int(j)))
    return out
