"""binpack - container loading for shipping.

The packing engine lives in the compiled ``pybinding`` module; everything it
exports is available here too, plus Python utilities:

* ``binpack.report``   - loading plans (``loading_plan``, ``format_plan``, ``plan_to_csv``, ``summary``)
* ``binpack.validate`` - independent audit of a plan (``validate``)
* ``binpack.pricing``  - freight tariffs that set ``Item.value``
* ``binpack.render``   - pictures and animations (needs matplotlib)
* ``binpack.bulk``     - bulk loads of one shaped product in its densest pattern (``pack_bulk``)
* ``binpack.crates``   - crates / trunks filled with goods, then loaded (``pack_with_crates``)
"""
from pybinding import (  # noqa: F401
    ALL_ROTATIONS,
    UNLIMITED,
    UPRIGHT_ROTATIONS,
    Axis,
    Bin,
    BinType,
    Box,
    FillOrder,
    FleetGoal,
    Item,
    LoadingAccess,
    Objective,
    Packer,
    RotationType,
    Shape,
)

from . import bulk, pricing, render, report  # noqa: F401
from .bulk import BulkPlan, bulk_layout, bulk_to_csv, format_bulk, pack_bulk  # noqa: F401
from .crates import CratePlan, CrateType, LoadingCrate, crate_manifest, format_crates, pack_with_crates  # noqa: F401
from .report import format_plan, loading_plan, plan_to_csv, summary  # noqa: F401
from .validate import Issue, validate, validate_bin  # noqa: F401
from .render import Palette, animate_loading, render_bin, render_fleet, render_loading_steps, render_packer  # noqa: F401
