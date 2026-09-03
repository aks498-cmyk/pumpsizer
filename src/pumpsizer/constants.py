"""Physical constants and small unit helpers.

Internally the engine works in strict SI:
    flow      Q   [m3/s]
    head      H   [m]  (metres of the pumped liquid)
    length/dia    [m]
    pressure      [Pa]
    power         [W]
The CLI / project files accept the field units engineers actually use
(l/s, m, mm, kW) and convert on the way in.
"""

from __future__ import annotations

G = 9.81  # m/s2, gravitational acceleration (matches the source workbook)
RHO_WATER_DEFAULT = 1000.0  # kg/m3
ATM_PRESSURE_SEA_LEVEL = 101_325.0  # Pa

# ---- flow ---------------------------------------------------------------
LPS_TO_M3S = 1.0e-3
M3S_TO_LPS = 1.0e3
M3H_TO_M3S = 1.0 / 3600.0
M3S_TO_M3H = 3600.0
MGD_US_TO_M3S = 0.0438126364
GPM_US_TO_M3S = 6.30902e-5


def lps(q_m3s: float) -> float:
    """m3/s -> l/s (for display)."""
    return q_m3s * M3S_TO_LPS


def m3h(q_m3s: float) -> float:
    """m3/s -> m3/h (for display)."""
    return q_m3s * M3S_TO_M3H


def pa_to_m(p_pa: float, rho: float = RHO_WATER_DEFAULT) -> float:
    """Pressure [Pa] -> head [m of liquid]."""
    return p_pa / (rho * G)


def m_to_pa(h_m: float, rho: float = RHO_WATER_DEFAULT) -> float:
    """Head [m of liquid] -> pressure [Pa]."""
    return h_m * rho * G
