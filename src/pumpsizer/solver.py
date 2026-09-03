"""Optional bridge to the EPANET 2.2 hydraulic solver via ``epyt``.

``pip install epyt`` (or ``pip install pumpsizer[epanet]``) to enable it.
Everything here degrades to a clear ImportError if epyt is absent.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path

# EPANET flow-unit -> litres/second
_FLOW_TO_LPS = {
    "LPS": 1.0,
    "LPM": 1 / 60.0,
    "MLD": 1_000_000.0 / 86_400.0,  # megalitres/day  -> 11.5741 l/s
    "CMH": 1_000.0 / 3_600.0,  # m3/h            -> 0.27778 l/s
    "CMD": 1_000.0 / 86_400.0,  # m3/day          -> 0.011574 l/s
    "CMS": 1_000.0,  # m3/s
    "GPM": 0.0630902,
    "MGD": 43.8126,
    "IMGD": 52.6168,
    "AFD": 14.2764,
    "CFS": 28.3168,
}
_US_UNITS = {"GPM", "MGD", "IMGD", "AFD", "CFS"}
_FT_TO_M = 0.3048


def available() -> bool:
    try:
        import epyt  # noqa: F401

        return True
    except Exception:
        return False


def _require_epyt():
    try:
        from epyt import epanet

        return epanet
    except Exception as exc:  # pragma: no cover
        raise ImportError(
            "the EPANET solver bridge needs 'epyt'.  Install it with "
            "`pip install epyt`  or  `pip install pumpsizer[epanet]`."
        ) from exc


@dataclass
class SimPumpResult:
    id: str
    node1: str
    node2: str
    flow_lps: float
    head_m: float  # head added by the pump (downstream - upstream)
    upstream_head_m: float
    downstream_head_m: float
    status: str

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "node1": self.node1,
            "node2": self.node2,
            "flow_lps": round(self.flow_lps, 3),
            "head_m": round(self.head_m, 3),
            "status": self.status,
        }


@dataclass
class SimResult:
    flow_units: str
    headloss: str
    pumps: list[SimPumpResult]
    warnings: list[str]

    def pump(self, pump_id: str) -> SimPumpResult:
        for p in self.pumps:
            if p.id == pump_id:
                return p
        raise KeyError(f"pump {pump_id!r} not in simulation results ({[p.id for p in self.pumps]})")


def simulate(inp_path: str | Path) -> SimResult:
    """Run a single-period hydraulic solve and return each pump's operating
    point, converted to l/s and metres regardless of the file's units."""
    epanet = _require_epyt()
    caught: list[str] = []
    with warnings.catch_warnings(record=True) as wlist:
        warnings.simplefilter("always")
        G = epanet(str(inp_path))
        try:
            units = str(G.getFlowUnits()).upper()
            to_lps = _FLOW_TO_LPS.get(units, 1.0)
            head_to_m = _FT_TO_M if units in _US_UNITS else 1.0

            try:
                G.setTimeSimulationDuration(0)
            except Exception:
                pass
            G.openHydraulicAnalysis()
            G.initializeHydraulicAnalysis()
            G.runHydraulicAnalysis()

            flows = list(G.getLinkFlows())
            node_head = list(G.getNodeHydraulicHead())
            link_nodes = G.getLinkNodesIndex()
            link_names = list(G.getLinkNameID())
            node_names = list(G.getNodeNameID())
            try:
                statuses = list(G.getLinkStatus())
            except Exception:
                statuses = [1] * len(flows)

            pidx = G.getLinkPumpIndex()
            pidx = [pidx] if isinstance(pidx, int) else list(pidx)

            pumps: list[SimPumpResult] = []
            for i in pidx:
                n1, n2 = link_nodes[i - 1]
                h1 = node_head[n1 - 1] * head_to_m
                h2 = node_head[n2 - 1] * head_to_m
                pumps.append(
                    SimPumpResult(
                        id=str(link_names[i - 1]),
                        node1=str(node_names[n1 - 1]),
                        node2=str(node_names[n2 - 1]),
                        flow_lps=flows[i - 1] * to_lps,
                        head_m=h2 - h1,
                        upstream_head_m=h1,
                        downstream_head_m=h2,
                        status=("open" if statuses[i - 1] else "closed"),
                    )
                )
            G.closeHydraulicAnalysis()
        finally:
            try:
                G.unload()
            except Exception:
                pass
    caught += [str(w.message) for w in wlist]
    return SimResult(flow_units=units, headloss="", pumps=pumps, warnings=caught)


def patch_and_simulate(
    inp_path: str | Path, export, *, output_path: str | Path | None = None
) -> tuple[SimResult, str]:
    """Splice ``export`` (a pumpsizer.epanet.EpanetPumpExport) into ``inp_path``,
    write the patched file (temp if ``output_path`` is None) and simulate it.
    Returns (SimResult, patched_inp_path)."""
    import tempfile

    from .inpfile import InpModel

    model = InpModel.read(inp_path)
    model.apply_export(export)
    if output_path is None:
        fd = tempfile.NamedTemporaryFile("w", suffix=".inp", delete=False, encoding="utf-8")
        fd.write(model.to_text())
        fd.close()
        out = fd.name
    else:
        model.write(output_path)
        out = str(output_path)
    return simulate(out), out
