"""Net Positive Suction Head available (NPSHa) and the cavitation-margin check.

Physically correct form (KSB "Selecting Centrifugal Pumps", sec. 3.5):

    NPSHa = (p_atm - p_v) / (rho g)  +  z_s,geo  -  H_L,s  -  v_s^2 / (2 g)

where ``z_s,geo`` is +ve when the supply level is ABOVE the pump reference
plane (flooded suction) and -ve for a suction lift.

The source workbook used  ``Patm - Hst - Hsf - Hsm - v^2/2g - SF``  with a
fixed ``Patm = 10 m`` and no vapour-pressure term.  Pass
``include_vapour_pressure=False`` and ``atmospheric_head=10.0`` to reproduce it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class NPSHResult:
    npsh_available_m: float
    npsh_required_m: float | None
    margin_m: float | None
    margin_ratio: float | None
    safe: bool | None
    terms: dict

    def as_dict(self) -> dict:
        return {
            "npsh_available_m": round(self.npsh_available_m, 3),
            "npsh_required_m": None
            if self.npsh_required_m is None
            else round(self.npsh_required_m, 3),
            "margin_m": None if self.margin_m is None else round(self.margin_m, 3),
            "margin_ratio": None if self.margin_ratio is None else round(self.margin_ratio, 3),
            "safe": self.safe,
            "terms": {k: round(v, 4) for k, v in self.terms.items()},
        }


def npsh_available(
    *,
    atmospheric_head_m: float,
    static_suction_head_m: float,
    suction_friction_loss_m: float,
    suction_minor_loss_m: float,
    suction_velocity_head_m: float,
    vapour_pressure_head_m: float = 0.0,
    safety_margin_m: float = 0.0,
    npsh_required_m: float | None = None,
    required_margin_m: float = 0.5,
) -> NPSHResult:
    """Compute NPSHa and, if ``npsh_required_m`` is given, the cavitation check.

    ``static_suction_head_m`` is +ve for flooded suction, -ve for suction lift.
    A common acceptance rule is NPSHa - NPSHr >= max(0.5 m, 0.1*NPSHr).
    """
    npsha = (
        atmospheric_head_m
        - vapour_pressure_head_m
        + static_suction_head_m
        - suction_friction_loss_m
        - suction_minor_loss_m
        - suction_velocity_head_m
        - safety_margin_m
    )

    terms = {
        "atmospheric_head_m": atmospheric_head_m,
        "vapour_pressure_head_m": vapour_pressure_head_m,
        "static_suction_head_m": static_suction_head_m,
        "suction_friction_loss_m": suction_friction_loss_m,
        "suction_minor_loss_m": suction_minor_loss_m,
        "suction_velocity_head_m": suction_velocity_head_m,
        "safety_margin_m": safety_margin_m,
    }

    if npsh_required_m is None:
        return NPSHResult(npsha, None, None, None, None, terms)

    margin = npsha - npsh_required_m
    ratio = (npsha / npsh_required_m) if npsh_required_m > 0 else float("inf")
    threshold = max(required_margin_m, 0.1 * npsh_required_m)
    return NPSHResult(npsha, npsh_required_m, margin, ratio, bool(margin >= threshold), terms)
