"""pumpsizer - water-supply pump sizing and EPANET-compatible curve generation.

Public API is intentionally small and stable; import submodules for detail.
"""
from __future__ import annotations

from . import epanet, solver, staging, surge, transient
from .catalog import Catalog, PumpModel
from .constants import RHO_WATER_DEFAULT, G
from .energy import annual_energy_cost, annual_energy_kwh, life_cycle_cost
from .fittings import FittingCatalog, minor_loss_k
from .fluid import WaterProperties, water_properties
from .friction import darcy_weisbach_hf, friction_factor, hazen_williams_hf
from .inpfile import InpModel
from .motor import MOTOR_KW_SERIES, MotorSelection, size_motor
from .npsh import NPSHResult, npsh_available
from .operating import (
    OperatingPoint,
    solve_operating_point,
    solve_parallel,
    solve_vfd_speed,
)
from .pipes import PipeDatabase, PipeSegment, select_diameter
from .project import Project, ProjectResults
from .pumpcurve import PumpCurve
from .selection import Candidate, SelectionCriteria, evaluate, select
from .system import SystemCurve, SystemCurveSet

try:                       # optional: needs openpyxl
    from . import excelio
except ImportError:         # pragma: no cover
    excelio = None  # type: ignore

__version__ = "0.1.0"

__all__ = [
    "MOTOR_KW_SERIES",
    "RHO_WATER_DEFAULT",
    "Candidate",
    "Catalog",
    "FittingCatalog",
    "G",
    "InpModel",
    "MotorSelection",
    "NPSHResult",
    "OperatingPoint",
    "PipeDatabase",
    "PipeSegment",
    "Project",
    "ProjectResults",
    "PumpCurve",
    "PumpModel",
    "SelectionCriteria",
    "SystemCurve",
    "SystemCurveSet",
    "WaterProperties",
    "__version__",
    "annual_energy_cost",
    "annual_energy_kwh",
    "darcy_weisbach_hf",
    "epanet",
    "evaluate",
    "excelio",
    "friction_factor",
    "hazen_williams_hf",
    "life_cycle_cost",
    "minor_loss_k",
    "npsh_available",
    "select",
    "select_diameter",
    "size_motor",
    "solve_operating_point",
    "solve_parallel",
    "solve_vfd_speed",
    "solver",
    "staging",
    "surge",
    "transient",
    "water_properties",
]
