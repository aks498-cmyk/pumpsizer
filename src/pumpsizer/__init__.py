"""pumpsizer - water-supply pump sizing and EPANET-compatible curve generation.

Public API is intentionally small and stable; import submodules for detail.
"""
from __future__ import annotations

from .constants import G, RHO_WATER_DEFAULT
from .fluid import WaterProperties, water_properties
from .friction import friction_factor, darcy_weisbach_hf, hazen_williams_hf
from .pipes import PipeDatabase, PipeSegment, select_diameter
from .fittings import FittingCatalog, minor_loss_k
from .system import SystemCurve, SystemCurveSet
from .pumpcurve import PumpCurve
from .operating import (
    OperatingPoint,
    solve_operating_point,
    solve_vfd_speed,
    solve_parallel,
)
from .npsh import npsh_available, NPSHResult
from .motor import size_motor, MotorSelection, MOTOR_KW_SERIES
from .energy import annual_energy_kwh, annual_energy_cost, life_cycle_cost
from .catalog import Catalog, PumpModel
from .selection import SelectionCriteria, Candidate, select, evaluate
from .project import Project, ProjectResults
from .inpfile import InpModel
from . import epanet
from . import solver
from . import surge

try:                       # optional: needs openpyxl
    from . import excelio
except ImportError:         # pragma: no cover
    excelio = None  # type: ignore

__version__ = "0.1.0"

__all__ = [
    "G",
    "RHO_WATER_DEFAULT",
    "WaterProperties",
    "water_properties",
    "friction_factor",
    "darcy_weisbach_hf",
    "hazen_williams_hf",
    "PipeDatabase",
    "PipeSegment",
    "select_diameter",
    "FittingCatalog",
    "minor_loss_k",
    "SystemCurve",
    "SystemCurveSet",
    "PumpCurve",
    "OperatingPoint",
    "solve_operating_point",
    "solve_vfd_speed",
    "solve_parallel",
    "npsh_available",
    "NPSHResult",
    "size_motor",
    "MotorSelection",
    "MOTOR_KW_SERIES",
    "annual_energy_kwh",
    "annual_energy_cost",
    "life_cycle_cost",
    "Catalog",
    "PumpModel",
    "SelectionCriteria",
    "Candidate",
    "select",
    "evaluate",
    "Project",
    "ProjectResults",
    "InpModel",
    "epanet",
    "solver",
    "surge",
    "excelio",
    "__version__",
]
