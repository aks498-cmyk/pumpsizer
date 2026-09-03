"""Pipe internal-diameter database and diameter selection by velocity."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import yaml


def _load_default_data() -> dict:
    with resources.files("pumpsizer.data").joinpath("pipes.yaml").open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@dataclass
class PipeDatabase:
    """Lookup of internal diameters, roughness and Hazen-Williams C by material."""

    materials: dict = field(default_factory=dict)
    water_bulk_modulus_gpa: float = 2.19

    @classmethod
    def default(cls) -> PipeDatabase:
        data = _load_default_data()
        return cls(materials=data["materials"],
                   water_bulk_modulus_gpa=data.get("water_bulk_modulus_gpa", 2.19))

    @classmethod
    def from_yaml(cls, path: str | Path) -> PipeDatabase:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return cls(materials=data["materials"],
                   water_bulk_modulus_gpa=data.get("water_bulk_modulus_gpa", 2.19))

    # -- elastic properties (water hammer) ----------------------------
    def youngs_modulus_gpa(self, material: str) -> float:
        spec = self.materials[self.material_key(material)]
        if "youngs_modulus_gpa" in spec:
            return float(spec["youngs_modulus_gpa"])
        raise KeyError(f"no youngs_modulus_gpa for {material!r} in the pipe DB")

    def wall_thickness_mm(self, material: str, dn: float,
                          series: str | None = None) -> float:
        """Representative wall thickness [mm] for a DN."""
        idmm = self.internal_diameter_mm(material, dn, series)
        return self.wall_thickness_from_id_mm(material, idmm, series)

    def wall_thickness_from_id_mm(self, material: str, id_mm: float,
                                  series: str | None = None) -> float:
        """Representative wall thickness [mm] from an internal diameter.
        Exact (OD/SDR) for HDPE/uPVC; ``wall_ratio_e_over_d`` x ID otherwise."""
        spec = self.materials[self.material_key(material)]
        if "outer_diameters_mm" in spec:                 # HDPE / uPVC
            series = series or spec.get("default_series")
            sdr = spec["series"][series]
            return id_mm / (sdr - 2.0)
        return id_mm * float(spec.get("wall_ratio_e_over_d", 0.03))

    # -- introspection --------------------------------------------------
    def material_key(self, name: str) -> str:
        """Resolve a user string ('Ductile Iron', 'ductile_iron', 'DI') to a key."""
        n = name.strip().lower().replace(" ", "_").replace("-", "_")
        if n in self.materials:
            return n
        aliases = {"di": "ductile_iron", "ci": "ductile_iron", "ms": "steel",
                   "pvc": "upvc", "pe": "hdpe", "frp": "grp"}
        if n in aliases and aliases[n] in self.materials:
            return aliases[n]
        for key, spec in self.materials.items():
            if spec.get("label", "").lower() == name.strip().lower():
                return key
        raise KeyError(f"unknown pipe material {name!r}; "
                       f"have {sorted(self.materials)}")

    def roughness_mm(self, material: str, condition: str = "new") -> float:
        spec = self.materials[self.material_key(material)]
        return float(spec[f"roughness_mm_{condition}"])

    def hazen_williams_c(self, material: str) -> float:
        return float(self.materials[self.material_key(material)]["hazen_williams_c"])

    def available_bores_mm(self, material: str, series: str | None = None) -> dict[float, float]:
        """Return {DN: internal_diameter_mm} for the material / series."""
        spec = self.materials[self.material_key(material)]
        if "sizes" in spec:
            return {float(dn): float(idmm) for dn, idmm in spec["sizes"].items()}
        series = series or spec.get("default_series")
        sdr = spec["series"][series]
        return {float(od): float(od) * (1.0 - 2.0 / sdr)
                for od in spec["outer_diameters_mm"]}

    def internal_diameter_mm(self, material: str, dn: float,
                             series: str | None = None) -> float:
        bores = self.available_bores_mm(material, series)
        if float(dn) not in bores:
            raise KeyError(f"DN{dn} not in {material} table "
                           f"({sorted(int(x) for x in bores)})")
        return bores[float(dn)]


@dataclass(frozen=True)
class PipeSegment:
    """One reach of pipe used to build a system curve."""

    name: str
    length_m: float
    diameter_mm: float
    roughness_mm: float
    hazen_williams_c: float = 130.0

    @property
    def diameter_m(self) -> float:
        return self.diameter_mm / 1000.0

    def velocity(self, q_m3s: float) -> float:
        d = self.diameter_m
        return 0.0 if d <= 0 else 4.0 * q_m3s / (math.pi * d * d)


@dataclass(frozen=True)
class DiameterChoice:
    material: str
    dn: float
    internal_diameter_mm: float
    velocity_at_q: float
    series: str | None = None


def select_diameter(db: PipeDatabase, material: str, q_m3s: float,
                    max_velocity: float, series: str | None = None
                    ) -> DiameterChoice:
    """Smallest catalogue bore whose full-bore velocity at ``q_m3s`` does not
    exceed ``max_velocity`` [m/s].  Falls back to the largest available bore
    (with a velocity above the limit) if nothing satisfies the constraint."""
    bores = db.available_bores_mm(material, series)
    ordered = sorted(bores.items(), key=lambda kv: kv[1])   # by bore
    best_fallback = None
    for dn, idmm in ordered:
        d = idmm / 1000.0
        v = 4.0 * q_m3s / (math.pi * d * d) if d > 0 else float("inf")
        best_fallback = DiameterChoice(material, dn, idmm, v, series)
        if v <= max_velocity:
            return DiameterChoice(material, dn, idmm, v, series)
    return best_fallback
