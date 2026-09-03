"""Manufacturer pump catalogue: data model + loader.

A catalogue file is YAML holding a list of pump models, each with one or more
published performance curves (Q vs H, and optionally efficiency, NPSHr, shaft
power) at a reference speed and impeller diameter.  See
``docs/catalog_template.yaml`` and ``src/pumpsizer/data/catalog/*.yaml``.

The bundled catalogue entries are illustrative shapes for testing the selection
engine - digitise the real curves from your datasheets before using them for
design (each entry carries a ``source`` / ``verified`` field).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import numpy as np
import yaml

from .constants import LPS_TO_M3S
from .pumpcurve import PumpCurve


@dataclass
class PumpModel:
    manufacturer: str
    series: str
    model: str
    reference_speed_rpm: float
    q_lps: list[float]
    h_m: list[float]
    eff_pct: list[float] | None = None
    npshr_m: list[float] | None = None
    shaft_power_kw: list[float] | None = None
    impeller_diameter_mm: float | None = None
    min_impeller_diameter_mm: float | None = None      # trim limit
    stages: int = 1
    poles: int = 2
    min_speed_ratio: float = 1.0                       # < 1 if VFD-rated
    max_speed_ratio: float = 1.0
    bore_suction_mm: float | None = None
    bore_discharge_mm: float | None = None
    price: float | None = None
    source: str = ""
    verified: bool = False
    notes: str = ""
    tags: list[str] = field(default_factory=list)

    # -- identity ------------------------------------------------------
    @property
    def key(self) -> str:
        return f"{self.manufacturer} {self.series} {self.model}".strip()

    @property
    def trim_limit_ratio(self) -> float:
        if self.impeller_diameter_mm and self.min_impeller_diameter_mm:
            return self.min_impeller_diameter_mm / self.impeller_diameter_mm
        return 0.80        # typical practical minimum trim

    # -- to a solvable curve ----------------------------------------
    def to_pump_curve(self, *, speed_ratio: float = 1.0,
                      diameter_ratio: float = 1.0) -> PumpCurve:
        q = np.asarray(self.q_lps, dtype=float) * LPS_TO_M3S
        h = np.asarray(self.h_m, dtype=float)
        curve = PumpCurve.from_points(
            q, h,
            eff=np.asarray(self.eff_pct, float) if self.eff_pct else None,
            eff_q=q if self.eff_pct else None,
            npshr=np.asarray(self.npshr_m, float) if self.npshr_m else None,
            npshr_q=q if self.npshr_m else None,
            name=self.key, prefer="auto",
        )
        if speed_ratio != 1.0 or diameter_ratio != 1.0:
            curve = curve.scaled(speed_ratio=speed_ratio, diameter_ratio=diameter_ratio)
        return curve

    @classmethod
    def from_dict(cls, d: dict) -> "PumpModel":
        curve = d.get("curve", d)
        known = cls.__dataclass_fields__
        payload = {k: v for k, v in {**d, **curve}.items() if k in known}
        return cls(**payload)


@dataclass
class Catalog:
    models: list[PumpModel] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.models)

    def __iter__(self):
        return iter(self.models)

    # -- loading -----------------------------------------------------
    @classmethod
    def bundled(cls) -> "Catalog":
        cat = cls()
        root = resources.files("pumpsizer.data").joinpath("catalog")
        for entry in root.iterdir():
            if entry.name.endswith((".yaml", ".yml")):
                cat.models.extend(_read_models(entry.read_text(encoding="utf-8")))
        return cat

    @classmethod
    def from_path(cls, path: str | Path) -> "Catalog":
        p = Path(path)
        files = sorted(p.glob("*.y*ml")) if p.is_dir() else [p]
        cat = cls()
        for f in files:
            cat.models.extend(_read_models(f.read_text(encoding="utf-8")))
        return cat

    def extend_from_path(self, path: str | Path) -> "Catalog":
        self.models.extend(Catalog.from_path(path).models)
        return self

    # -- filtering -------------------------------------------------
    def filter(self, *, manufacturer: str | None = None, series: str | None = None,
               poles: int | None = None, tag: str | None = None,
               verified_only: bool = False) -> "Catalog":
        def ok(m: PumpModel) -> bool:
            return (
                (manufacturer is None or manufacturer.lower() in m.manufacturer.lower())
                and (series is None or series.lower() in m.series.lower())
                and (poles is None or m.poles == poles)
                and (tag is None or tag in m.tags)
                and (not verified_only or m.verified)
            )
        return Catalog([m for m in self.models if ok(m)])

    def get(self, key: str) -> PumpModel:
        for m in self.models:
            if m.key.lower() == key.lower() or m.model.lower() == key.lower():
                return m
        raise KeyError(f"no pump {key!r} in catalogue ({[m.key for m in self.models]})")


def _read_models(text: str) -> list[PumpModel]:
    data = yaml.safe_load(text)
    if data is None:
        return []
    items = data["pumps"] if isinstance(data, dict) and "pumps" in data else data
    return [PumpModel.from_dict(d) for d in items]
