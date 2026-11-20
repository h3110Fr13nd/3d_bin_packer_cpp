"""Freight tariffs: turn items into revenue (``Item.value``) so the packer can
maximise what a load earns (``Packer(objective=Objective.VALUE)``).

A tariff is any function ``Shipment -> charge``. Build one from the common
models below, add minimums or surcharges, then price your items::

    from binpack import pricing
    tariff = pricing.minimum(pricing.weight_or_measure(rate_per_revenue_ton=45.0), 45.0)
    pricing.price_items(items, tariff, unit="mm")   # sets item.value
    packer = Packer(objective=Objective.VALUE)

Items that share a ``group`` (a consignment) are priced together, the way
carriers invoice: chargeable weight, minimum charges etc. apply per
consignment, and the charge is split over its items. A consignment is only
worth its full charge when loaded complete, which the packer guarantees
(groups are loaded complete or not at all).

Weights are taken as kilograms. Lengths are converted with ``unit``.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import Callable, Iterable

_METERS = {"mm": 1e-3, "cm": 1e-2, "dm": 1e-1, "m": 1.0, "in": 0.0254, "ft": 0.3048}


@dataclass(frozen=True)
class Shipment:
    """Chargeable measures of one item or one consignment."""

    weight_kg: float
    volume_m3: float
    floor_area_m2: float   # footprint as shipped (width x depth)
    pieces: int
    non_stackable: bool = False  # any piece that nothing may be stacked on


Tariff = Callable[[Shipment], float]


def measure(items: Iterable, unit: str = "mm") -> Shipment:
    """Aggregated measures of the given items (dimensions in ``unit``)."""
    s = _METERS[unit]
    items = list(items)
    return Shipment(
        weight_kg=sum(it.weight for it in items),
        volume_m3=sum(it.width * it.height * it.depth for it in items) * s ** 3,
        floor_area_m2=sum(it.width * it.depth for it in items) * s ** 2,
        pieces=len(items),
        non_stackable=any(it.is_disable_stacking() or it.is_height_constrained() for it in items),
    )


# --------------------------------------------------------------- base tariffs --

def per_kg(rate: float) -> Tariff:
    """Actual weight only (dense cargo, bulk)."""
    return lambda s: rate * s.weight_kg


def per_m3(rate: float) -> Tariff:
    """Volume only (light cargo, removals)."""
    return lambda s: rate * s.volume_m3


def per_piece(rate: float) -> Tariff:
    """Flat rate per package/pallet (parcels, pallet networks)."""
    return lambda s: rate * s.pieces


def chargeable_weight(rate_per_kg: float, divisor_cm3_per_kg: float = 6000.0) -> Tariff:
    """Air freight / express: max(actual, volumetric weight).

    Volumetric kg = volume in cm3 / divisor. IATA air cargo uses 6000;
    express couriers typically 5000 (some 4000).
    """
    def tariff(s: Shipment) -> float:
        volumetric = s.volume_m3 * 1e6 / divisor_cm3_per_kg
        return rate_per_kg * max(s.weight_kg, volumetric)
    return tariff


def weight_or_measure(rate_per_revenue_ton: float, kg_per_m3: float = 1000.0) -> Tariff:
    """Sea freight LCL (W/M): charged per revenue ton = max(tonnes, m3).

    ``kg_per_m3`` is the weight equivalent of one cubic metre (1000 for ocean).
    """
    return lambda s: rate_per_revenue_ton * max(s.weight_kg / kg_per_m3, s.volume_m3)


def road_chargeable_weight(rate_per_kg: float, kg_per_m3: float = 333.0) -> Tariff:
    """Road groupage / LTL in Europe: max(actual kg, m3 x 333) (1:3 ratio)."""
    return lambda s: rate_per_kg * max(s.weight_kg, s.volume_m3 * kg_per_m3)


def loading_meters(rate_per_ldm: float, trailer_width_m: float = 2.4,
                   kg_per_ldm: float | None = 1850.0) -> Tariff:
    """Road freight by loading metre: floor length used across the trailer width.

    LDM = floor area / trailer width. Heavy goods are charged by weight
    equivalent when that is more (``kg_per_ldm``; None to disable).
    """
    def tariff(s: Shipment) -> float:
        ldm = s.floor_area_m2 / trailer_width_m
        if kg_per_ldm:
            ldm = max(ldm, s.weight_kg / kg_per_ldm)
        return rate_per_ldm * ldm
    return tariff


# NMFC density-based classes: (minimum pounds per cubic foot, class).
_DENSITY_CLASSES = [(0, 500), (1, 400), (2, 300), (3, 250), (4, 200), (5, 175), (6, 150), (7, 125),
                    (8, 110), (9, 100), (10.5, 92.5), (12, 85), (13.5, 77.5), (15, 70), (22.5, 65),
                    (30, 60), (35, 55), (50, 50)]


def freight_class(s: Shipment) -> float:
    """US LTL freight class from density (lb/ft3), NMFC density scale."""
    pounds = s.weight_kg * 2.20462
    cubic_feet = s.volume_m3 * 35.3147
    density = pounds / cubic_feet if cubic_feet > 0 else float("inf")
    thresholds = [t for t, _ in _DENSITY_CLASSES]
    return _DENSITY_CLASSES[bisect.bisect_right(thresholds, density) - 1][1]


def ltl_density_class(rate_per_cwt_by_class: dict[float, float]) -> Tariff:
    """US LTL: rate per hundredweight (100 lb), looked up by density class.

    ``rate_per_cwt_by_class`` maps freight class (50 ... 500) to the rate;
    classes missing from the table use the next higher class listed.
    """
    classes = sorted(rate_per_cwt_by_class)

    def tariff(s: Shipment) -> float:
        cls = freight_class(s)
        i = bisect.bisect_left(classes, cls)
        rate = rate_per_cwt_by_class[classes[min(i, len(classes) - 1)]]
        return rate * s.weight_kg * 2.20462 / 100.0
    return tariff


# ---------------------------------------------------------------- modifiers --

def minimum(tariff: Tariff, amount: float) -> Tariff:
    """Minimum charge per consignment."""
    return lambda s: max(amount, tariff(s))


def surcharge(tariff: Tariff, percent: float = 0.0, flat: float = 0.0, per_piece: float = 0.0,
              non_stackable_percent: float = 0.0) -> Tariff:
    """Adds e.g. fuel (percent), documentation (flat), handling (per piece)
    and a surcharge for non-stackable goods, which block the space above them."""
    def wrapped(s: Shipment) -> float:
        base = tariff(s)
        pct = percent + (non_stackable_percent if s.non_stackable else 0.0)
        return base * (1 + pct / 100.0) + flat + per_piece * s.pieces
    return wrapped


def highest(*tariffs: Tariff) -> Tariff:
    """Charge the highest of several tariffs (e.g. per kg vs per LDM)."""
    return lambda s: max(t(s) for t in tariffs)


def profit(revenue: Tariff, cost: Tariff) -> Tariff:
    """Revenue minus your cost (handling, last mile, ...), to maximise margin."""
    return lambda s: revenue(s) - cost(s)


# ------------------------------------------------------------------ pricing --

def price_items(items: Iterable, tariff: Tariff, unit: str = "mm", by_group: bool = True) -> float:
    """Sets ``item.value`` from the tariff and returns the total.

    With ``by_group`` the items of a consignment (same non-empty ``group``)
    are charged together and the consignment's charge is split over its
    items in proportion to what each would cost alone.

    Set values *before* ``packer.add_item(item)``: the packer stores copies.
    """
    items = list(items)
    groups: dict[str, list] = {}
    for it in items:
        key = it.group if (by_group and it.group) else f"\0{id(it)}"
        groups.setdefault(key, []).append(it)
    total = 0.0
    for members in groups.values():
        charge = tariff(measure(members, unit))
        alone = [max(0.0, tariff(measure([it], unit))) for it in members]
        weight_sum = sum(alone)
        for it, a in zip(members, alone):
            it.value = charge * (a / weight_sum if weight_sum > 0 else 1.0 / len(members))
        total += charge
    return total
