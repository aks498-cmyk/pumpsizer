"""Driver (electric motor) sizing.

* shaft power from the operating point (or the non-overloading maximum along
  the pump curve),
* a rating margin,
* rounding up to the IEC 60072-1 preferred kW series,
* nominal efficiency from the IE-class table (workbook "Motor Rating" sheet).
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import resources

import numpy as np
import yaml


def _load() -> dict:
    with resources.files("pumpsizer.data").joinpath("motors.yaml").open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


_DATA = _load()
MOTOR_KW_SERIES: list[float] = list(_DATA["kw_series"])
_EFF_BANDS: list[float] = list(_DATA["efficiency_kw_bands"])
_EFF: dict = _DATA["efficiency"]


def next_standard_kw(value_kw: float) -> float:
    for s in MOTOR_KW_SERIES:
        if s >= value_kw - 1e-9:
            return s
    return MOTOR_KW_SERIES[-1]


def nominal_efficiency(rated_kw: float, poles: int = 2, ie_class: str = "IE3") -> float:
    """Nominal motor efficiency [%] for a rated output, pole count and IE class.
    Reads the first table band whose kW >= ``rated_kw`` (matches the workbook's
    ascending MATCH)."""
    ie_class = ie_class.upper()
    if ie_class not in _EFF:
        raise KeyError(f"IE class {ie_class!r} not in {sorted(_EFF)}")
    if poles not in _EFF[ie_class]:
        poles = min(_EFF[ie_class], key=lambda p: abs(p - poles))
    row = _EFF[ie_class][poles]
    bands = np.array(_EFF_BANDS, dtype=float)
    idx = int(np.argmin(np.where(bands >= rated_kw, bands, np.inf)))
    if bands[idx] < rated_kw:
        idx = 0
    return float(row[idx])


@dataclass
class MotorSelection:
    shaft_power_kw: float
    design_basis: str
    margin_pct: float
    required_kw: float
    rated_kw: float
    poles: int
    ie_class: str
    motor_efficiency_pct: float
    input_electrical_kw: float

    def as_dict(self) -> dict:
        return {
            "shaft_power_kw": round(self.shaft_power_kw, 3),
            "design_basis": self.design_basis,
            "margin_pct": self.margin_pct,
            "required_kw": round(self.required_kw, 3),
            "rated_kw": self.rated_kw,
            "poles": self.poles,
            "ie_class": self.ie_class,
            "motor_efficiency_pct": round(self.motor_efficiency_pct, 2),
            "input_electrical_kw": round(self.input_electrical_kw, 3),
        }


def size_motor(shaft_power_kw: float, *, margin_pct: float = 15.0,
               poles: int = 2, ie_class: str = "IE3",
               design_basis: str = "operating point") -> MotorSelection:
    """Round ``shaft_power_kw * (1 + margin)`` up to a standard motor and report
    its nominal efficiency and electrical input power."""
    required = shaft_power_kw * (1.0 + margin_pct / 100.0)
    rated = next_standard_kw(required)
    eff = nominal_efficiency(rated, poles=poles, ie_class=ie_class)
    input_kw = shaft_power_kw / (eff / 100.0)
    return MotorSelection(
        shaft_power_kw=shaft_power_kw, design_basis=design_basis,
        margin_pct=margin_pct, required_kw=required, rated_kw=rated,
        poles=poles, ie_class=ie_class, motor_efficiency_pct=eff,
        input_electrical_kw=input_kw,
    )


def non_overloading_shaft_power_kw(pump_curve, rho: float = 1000.0, g: float = 9.81,
                                   q_max: float | None = None) -> float:
    """Maximum shaft power along the pump curve from ~0 to runout - the basis
    for a 'non-overloading' motor selection."""
    q_max = q_max if q_max is not None else pump_curve.max_flow()
    q = np.linspace(1e-4, q_max, 200)
    return float(np.max(pump_curve.shaft_power(q, rho, g)) / 1000.0)
