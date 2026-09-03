"""Minor-loss coefficient catalog and helpers."""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import yaml


def _load_default_data() -> dict:
    with resources.files("pumpsizer.data").joinpath("fittings.yaml").open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@dataclass
class FittingCatalog:
    """Named minor-loss coefficients K in  h = K * v^2 / (2 g)."""

    coefficients: dict = field(default_factory=dict)

    @classmethod
    def default(cls) -> "FittingCatalog":
        data = _load_default_data()
        merged: dict = {}
        merged.update(data.get("extra", {}))
        merged.update(data.get("workbook_defaults", {}))   # workbook wins on clashes
        return cls(coefficients={k: float(v) for k, v in merged.items()})

    @classmethod
    def from_yaml(cls, path: str | Path) -> "FittingCatalog":
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        flat: dict = {}
        for section in ("extra", "workbook_defaults"):
            flat.update(data.get(section, {}))
        flat.update({k: v for k, v in data.items()
                     if k not in ("extra", "workbook_defaults") and not isinstance(v, dict)})
        return cls(coefficients={k: float(v) for k, v in flat.items()})

    def k(self, name: str) -> float:
        key = name.strip().lower().replace(" ", "_").replace("-", "_").replace("__", "_")
        aliases = {
            "bellmouth": "entrance_bellmouth", "entrance": "entrance_bellmouth",
            "90_bend": "bend_90", "90deg_bend": "bend_90", "elbow_90": "bend_90",
            "45_bend": "bend_45", "22_5_bend": "bend_22_5", "22.5_bend": "bend_22_5",
            "nrv": "non_return_valve", "check_valve": "non_return_valve",
            "bfv": "butterfly_valve", "sluice_valve": "gate_valve",
            "exit": "exit_sharp", "enlarger": "enlarger", "expander": "enlarger",
        }
        key = aliases.get(key, key)
        if key not in self.coefficients:
            raise KeyError(f"unknown fitting {name!r}; have {sorted(self.coefficients)}")
        return self.coefficients[key]

    def total_k(self, items: dict[str, float]) -> float:
        """Sum of K for a ``{fitting_name: quantity}`` mapping."""
        return sum(self.k(name) * float(qty) for name, qty in items.items())


def minor_loss_k(catalog: FittingCatalog, items: dict[str, float]) -> float:
    """Free-function form of :meth:`FittingCatalog.total_k`."""
    return catalog.total_k(items)
