"""Energy use and a simple life-cycle-cost helper."""

from __future__ import annotations


def annual_energy_kwh(
    input_electrical_kw: float, hours_per_day: float, days_per_year: float = 365.0
) -> float:
    """Annual electrical energy [kWh] for a steady operating point."""
    return input_electrical_kw * hours_per_day * days_per_year


def annual_energy_cost(
    energy_kwh: float,
    tariff_per_kwh: float,
    demand_charge_per_kw_month: float = 0.0,
    rated_kw: float = 0.0,
) -> float:
    """Annual energy cost = energy charge + optional monthly demand charge."""
    return energy_kwh * tariff_per_kwh + demand_charge_per_kw_month * rated_kw * 12.0


def present_value_factor(discount_rate: float, years: int) -> float:
    """Sum of 1/(1+r)^t for t = 1..years  (annuity present-worth factor)."""
    if discount_rate <= 0:
        return float(years)
    return (1.0 - (1.0 + discount_rate) ** -years) / discount_rate


def life_cycle_cost(
    capital_cost: float,
    annual_energy_cost_value: float,
    annual_maintenance_cost: float = 0.0,
    *,
    years: int = 20,
    discount_rate: float = 0.08,
) -> dict:
    """Present-value life-cycle cost over ``years`` at ``discount_rate``."""
    pwf = present_value_factor(discount_rate, years)
    pv_energy = annual_energy_cost_value * pwf
    pv_maint = annual_maintenance_cost * pwf
    return {
        "capital_cost": round(capital_cost, 2),
        "pv_energy": round(pv_energy, 2),
        "pv_maintenance": round(pv_maint, 2),
        "life_cycle_cost": round(capital_cost + pv_energy + pv_maint, 2),
        "years": years,
        "discount_rate": discount_rate,
        "present_worth_factor": round(pwf, 4),
    }
