"""Minimal structured reader/writer for EPANET 2.x ``.inp`` files.

No external dependency.  Preserves section order, comments and unknown
sections verbatim; gives typed access to the bits this tool needs
(``[OPTIONS]``, ``[CURVES]``, ``[PUMPS]``, ``[ENERGY]``) and safe upserts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_SECTION_RE = re.compile(r"^\s*\[([A-Za-z_]+)\]\s*(;.*)?$")


def _split_inline_comment(line: str) -> tuple[str, str]:
    i = line.find(";")
    return (line, "") if i < 0 else (line[:i], line[i:])


def _tokens(line: str) -> list[str]:
    code, _ = _split_inline_comment(line)
    return code.split()


@dataclass
class PumpRecord:
    id: str
    node1: str
    node2: str
    params: dict[str, str] = field(default_factory=dict)   # HEAD/POWER/SPEED/PATTERN
    comment: str = ""

    def to_line(self) -> str:
        parts = [f" {self.id:<16}{self.node1:<16}{self.node2:<16}"]
        for key in ("HEAD", "POWER", "SPEED", "PATTERN"):
            if key in self.params:
                parts.append(f"{key} {self.params[key]}")
        line = "  ".join(p.strip() if i else p for i, p in enumerate(parts))
        return f" {line}{('   ' + self.comment) if self.comment else ''}"


@dataclass
class InpModel:
    """Ordered ``{SECTION: [lines]}`` with typed helpers."""

    order: list[str] = field(default_factory=list)
    sections: dict[str, list[str]] = field(default_factory=dict)

    # ------------------------------------------------------------------
    @classmethod
    def parse(cls, text: str) -> InpModel:
        m = cls()
        current = "_PREAMBLE"
        m.order.append(current)
        m.sections[current] = []
        for raw in text.splitlines():
            hit = _SECTION_RE.match(raw)
            if hit:
                current = hit.group(1).upper()
                if current not in m.sections:
                    m.sections[current] = []
                    m.order.append(current)
                continue
            m.sections.setdefault(current, []).append(raw)
        return m

    @classmethod
    def read(cls, path: str | Path) -> InpModel:
        return cls.parse(Path(path).read_text())

    def to_text(self) -> str:
        out: list[str] = []
        for sec in self.order:
            if sec != "_PREAMBLE":
                out.append(f"[{sec}]")
            out.extend(self.sections.get(sec, []))
        if "END" not in self.sections:
            out.append("[END]")
        return "\n".join(out).rstrip() + "\n"

    def write(self, path: str | Path) -> None:
        Path(path).write_text(self.to_text())

    # ------------------------------------------------------------------
    def _ensure(self, sec: str) -> list[str]:
        if sec not in self.sections:
            self.sections[sec] = []
            insert_before = self.order.index("END") if "END" in self.order else len(self.order)
            self.order.insert(insert_before, sec)
        return self.sections[sec]

    # -- OPTIONS ---------------------------------------------------
    def option(self, key: str, default: str | None = None) -> str | None:
        for line in self.sections.get("OPTIONS", []):
            tok = _tokens(line)
            if len(tok) >= 2 and " ".join(tok[:-1]).upper() == key.upper():
                return tok[-1]
            if tok and tok[0].upper() == key.upper() and len(tok) >= 2:
                return tok[1]
        return default

    @property
    def flow_units(self) -> str:
        return (self.option("UNITS") or "GPM").upper()

    @property
    def headloss(self) -> str:
        return (self.option("HEADLOSS") or "H-W").upper()

    # -- CURVES --------------------------------------------------
    def curve_points(self, curve_id: str) -> list[tuple[float, float]]:
        pts = []
        for line in self.sections.get("CURVES", []):
            tok = _tokens(line)
            if len(tok) >= 3 and tok[0] == curve_id:
                pts.append((float(tok[1]), float(tok[2])))
        return pts

    def upsert_curve(self, curve_id: str, points: list[tuple[float, float]],
                     kind: str = "PUMP") -> None:
        body = self._ensure("CURVES")
        kept = [ln for ln in body if not (_tokens(ln)[:1] == [curve_id])]
        block = [f";{kind}: {curve_id}"]
        block += [f" {curve_id:<16}{x:<14.6g}{y:.6g}" for x, y in points]
        self.sections["CURVES"] = kept + block

    # -- PUMPS --------------------------------------------------
    @property
    def pumps(self) -> list[PumpRecord]:
        recs = []
        for line in self.sections.get("PUMPS", []):
            tok = _tokens(line)
            if len(tok) < 3:
                continue
            _, cmt = _split_inline_comment(line)
            params: dict[str, str] = {}
            rest = tok[3:]
            i = 0
            while i < len(rest) - 1:
                params[rest[i].upper()] = rest[i + 1]
                i += 2
            recs.append(PumpRecord(tok[0], tok[1], tok[2], params, cmt.strip()))
        return recs

    def upsert_pump(self, pump_id: str, node1: str, node2: str, *,
                    head_curve: str | None = None, power_kw: float | None = None,
                    speed: float | None = None, pattern: str | None = None,
                    keep_existing_nodes: bool = True) -> None:
        body = self._ensure("PUMPS")
        if keep_existing_nodes:
            for rec in self.pumps:
                if rec.id == pump_id:
                    node1, node2 = rec.node1, rec.node2      # don't move the pump
                    break
        params: dict[str, str] = {}
        if head_curve:
            params["HEAD"] = head_curve
        if power_kw is not None:
            params["POWER"] = f"{power_kw:.6g}"
        if speed is not None and abs(speed - 1.0) > 1e-9:
            params["SPEED"] = f"{speed:.6g}"
        if pattern:
            params["PATTERN"] = pattern
        rec = PumpRecord(pump_id, node1, node2, params)
        kept = [ln for ln in body if _tokens(ln)[:1] != [pump_id]]
        self.sections["PUMPS"] = kept + [rec.to_line()]

    # -- ENERGY -------------------------------------------------
    def set_pump_energy(self, pump_id: str, *, effic_curve: str | None = None,
                        price: float | None = None, pattern: str | None = None) -> None:
        body = self._ensure("ENERGY")
        def keep(ln: str) -> bool:
            tok = _tokens(ln)
            return not (len(tok) >= 2 and tok[0].upper() == "PUMP" and tok[1] == pump_id)
        kept = [ln for ln in body if keep(ln)]
        add = []
        if effic_curve:
            add.append(f" PUMP {pump_id}  EFFIC   {effic_curve}")
        if price is not None:
            add.append(f" PUMP {pump_id}  PRICE   {price:.6g}")
        if pattern:
            add.append(f" PUMP {pump_id}  PATTERN {pattern}")
        self.sections["ENERGY"] = kept + add

    # -- convenience --------------------------------------------
    def apply_export(self, export, *, move_pump: bool = False) -> InpModel:
        """Splice a :class:`pumpsizer.epanet.EpanetPumpExport` into this model.

        If a pump with ``export.pump_id`` already exists its end nodes are kept
        (only the head curve / speed / pattern change) unless ``move_pump`` is
        set - so ``export.from_node`` / ``to_node`` only matter when adding a
        brand-new pump.
        """
        self.upsert_curve(export.head_curve_id, export.head_points, "PUMP")
        if export.efficiency_points and export.efficiency_curve_id:
            self.upsert_curve(export.efficiency_curve_id, export.efficiency_points,
                              "EFFICIENCY")
        self.upsert_pump(export.pump_id, export.from_node, export.to_node,
                         head_curve=export.head_curve_id,
                         speed=export.speed if abs(export.speed - 1.0) > 1e-9 else None,
                         pattern=export.speed_pattern,
                         keep_existing_nodes=not move_pump)
        if export.efficiency_curve_id or export.price_per_kwh is not None:
            self.set_pump_energy(export.pump_id,
                                 effic_curve=export.efficiency_curve_id,
                                 price=export.price_per_kwh,
                                 pattern=export.price_pattern)
        return self
