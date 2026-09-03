"""Properties of water as a function of temperature and site altitude.

The kinematic-viscosity table is taken verbatim from the ``Viscousity`` sheet of
the source workbook (``Pump Sizing.xlsx``) so that Reynolds numbers and friction
factors reproduce the spreadsheet.  Vapour pressure and density come from
standard steam-table data (needed for a correct NPSH check, which the workbook
omitted).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .constants import ATM_PRESSURE_SEA_LEVEL, G

# temperature [degC], kinematic viscosity [m2/s]   (workbook Viscousity!B/G columns)
_NU_TABLE_T = np.array(
    [
        0.01,
        10,
        20,
        25,
        30,
        40,
        50,
        60,
        70,
        80,
        90,
        100,
        110,
        120,
        140,
        160,
        180,
        200,
        220,
        240,
        260,
        280,
        300,
        320,
        340,
        360,
    ]
)
_NU_TABLE_NU = (
    np.array(
        [
            1.7918,
            1.3065,
            1.0035,
            0.8927,
            0.8007,
            0.6579,
            0.5531,
            0.4740,
            0.4127,
            0.3643,
            0.3255,
            0.2938,
            0.2677,
            0.2460,
            0.2123,
            0.1878,
            0.1695,
            0.1556,
            0.1449,
            0.1365,
            0.1299,
            0.1247,
            0.1206,
            0.1174,
            0.1152,
            0.1143,
        ]
    )
    * 1.0e-6
)

# temperature [degC], saturation (vapour) pressure [Pa], density [kg/m3]
_T_STEAM = np.array([0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 90, 100])
_PV_STEAM = np.array(
    [
        611,
        872,
        1228,
        1706,
        2339,
        3169,
        4246,
        5628,
        7384,
        9593,
        12_349,
        19_946,
        31_201,
        47_414,
        70_182,
        101_420.0,
    ]
)
_RHO_STEAM = np.array(
    [
        999.8,
        1000.0,
        999.7,
        999.1,
        998.2,
        997.0,
        995.6,
        994.0,
        992.2,
        990.2,
        988.0,
        983.2,
        977.8,
        971.8,
        965.3,
        958.4,
    ]
)


def kinematic_viscosity(temp_c: float) -> float:
    """Kinematic viscosity of water [m2/s] at ``temp_c`` (linear interpolation,
    matching the ``FORECAST``-style interpolation used in the workbook)."""
    return float(np.interp(temp_c, _NU_TABLE_T, _NU_TABLE_NU))


def vapour_pressure(temp_c: float) -> float:
    """Saturation vapour pressure of water [Pa]."""
    return float(np.interp(temp_c, _T_STEAM, _PV_STEAM))


def density(temp_c: float) -> float:
    """Density of water [kg/m3]."""
    return float(np.interp(temp_c, _T_STEAM, _RHO_STEAM))


def atmospheric_pressure(altitude_m: float = 0.0) -> float:
    """Local mean atmospheric pressure [Pa] from the barometric formula
    (ISA troposphere, 0-11 km).  ``altitude_m`` is site elevation above MSL."""
    if altitude_m <= 0:
        return ATM_PRESSURE_SEA_LEVEL
    return ATM_PRESSURE_SEA_LEVEL * (1.0 - 2.25577e-5 * altitude_m) ** 5.25588


@dataclass(frozen=True)
class WaterProperties:
    """Bundle of water properties for one operating condition."""

    temperature_c: float
    altitude_m: float
    density: float  # kg/m3
    kinematic_viscosity: float  # m2/s
    vapour_pressure: float  # Pa
    atmospheric_pressure: float  # Pa

    @property
    def vapour_pressure_head(self) -> float:
        """Vapour pressure expressed as head of the liquid [m]."""
        return self.vapour_pressure / (self.density * G)

    @property
    def atmospheric_pressure_head(self) -> float:
        """Atmospheric pressure expressed as head of the liquid [m]."""
        return self.atmospheric_pressure / (self.density * G)


def water_properties(temp_c: float = 20.0, altitude_m: float = 0.0) -> WaterProperties:
    """Construct :class:`WaterProperties` for the given temperature and altitude."""
    return WaterProperties(
        temperature_c=temp_c,
        altitude_m=altitude_m,
        density=density(temp_c),
        kinematic_viscosity=kinematic_viscosity(temp_c),
        vapour_pressure=vapour_pressure(temp_c),
        atmospheric_pressure=atmospheric_pressure(altitude_m),
    )
