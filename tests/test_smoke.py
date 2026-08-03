"""Smoke tests for Live Event Operations — offline gate (no Fabric needed).

Validates: Python compiles, config/state parse, and the synthetic data generator produces a
coherent topology + an embedded congestion peak the Operations Agent can RCA.

Run BEFORE any deploy:  python -m pytest tests/ -v --tb=short
"""
import ast
import json
import pathlib
import re
import sys

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


# ── Python compiles ─────────────────────────────────────────────
def _py_files():
    return sorted(SRC.rglob("*.py"))


@pytest.mark.parametrize("py", _py_files(), ids=lambda p: p.name)
def test_python_compiles(py):
    ast.parse(py.read_text(encoding="utf-8"), filename=str(py))


# ── Cross-platform guards (the repo must import on macOS / Linux too) ──
def test_no_module_level_winreg_import():
    """`winreg` is Windows-only stdlib: importing it unconditionally breaks macOS/Linux."""
    offenders = []
    for py in _py_files():
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in tree.body:  # module level only — a guarded import lives deeper
            if isinstance(node, ast.Import) and any(a.name == "winreg" for a in node.names):
                offenders.append(py.name)
    assert not offenders, f"winreg imported unconditionally in: {offenders}"


def test_restore_path_is_inert_off_windows():
    """Off Windows there is no registry: restore_path() must leave PATH untouched."""
    import importlib
    import os

    pe = importlib.import_module("platform_env")
    real_platform = sys.platform
    try:
        sys.platform = "linux"
        sys.modules["winreg"] = None  # any `import winreg` now raises
        pe = importlib.reload(pe)
        assert pe.IS_WINDOWS is False
        assert pe.AZ_NEEDS_SHELL is False, "shell=True with an argv list breaks on POSIX"
        before = os.environ.get("PATH", "")
        pe.restore_path()
        assert os.environ.get("PATH", "") == before, "PATH must be untouched off Windows"
    finally:
        sys.platform = real_platform
        sys.modules.pop("winreg", None)
        importlib.reload(pe)


def test_find_executable_uses_the_standard_path(tmp_path, monkeypatch):
    """find_executable() must resolve through the standard environment PATH."""
    import platform_env

    binary = tmp_path / ("fake-tool.bat" if platform_env.IS_WINDOWS else "fake-tool")
    binary.write_text("echo hi\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))

    found = platform_env.find_executable("fake-tool")
    assert found is not None
    assert pathlib.Path(found).name.lower() == binary.name.lower()  # PATHEXT is uppercased
    assert platform_env.find_executable("no-such-executable-fab-live-event") is None


def test_scripts_share_the_canonical_prologue():
    """Every script bootstrapping the environment must use the same 3 lines.

    `src/platform_env.py` is shared verbatim with the sister repository, so the
    call-site prologue has to stay byte-identical on both sides.
    """
    prologue = re.compile(
        r"^import os, sys[^\n]*\n"
        r"from platform_env import bootstrap\n"
        r"bootstrap\(\)\n",
        re.MULTILINE,
    )
    scripts = [p for p in _py_files()
               if p.name != "platform_env.py"
               and "from platform_env import bootstrap" in p.read_text(encoding="utf-8")]
    assert scripts, "no script bootstraps platform_env — did the prologue get renamed?"
    for py in scripts:
        assert prologue.search(py.read_text(encoding="utf-8")), \
            f"{py.name}: non-canonical platform_env prologue"


def test_az_is_never_launched_with_a_bare_shell_true():
    """`shell=True` + an argv list drops every argument on POSIX — use AZ_NEEDS_SHELL."""
    offenders = []
    for py in _py_files():
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if (kw.arg == "shell"
                        and isinstance(kw.value, ast.Constant)
                        and kw.value.value is True):
                    offenders.append(f"{py.name}:{node.lineno}")
    assert not offenders, f"hard-coded shell=True in: {offenders}"


# ── Config / state ──────────────────────────────────────────────
def _config_path() -> pathlib.Path:
    """Prefer the local (gitignored) config.yaml, fall back to the committed example."""
    local = SRC / "config.yaml"
    return local if local.exists() else SRC / "config.example.yaml"


def test_config_parses_and_has_keys():
    cfg = yaml.safe_load(_config_path().read_text(encoding="utf-8"))
    for key in ["workspace_name", "fabric_api_base", "lakehouse_name", "eventhouse_name",
                "ontology_name", "operations_agent_name", "culprit_gate", "telemetry",
                "edition", "zones", "customers", "sessions"]:
        assert key in cfg, f"config missing '{key}'"
    assert cfg["culprit_gate"].startswith("GATE-")
    assert len(cfg["zones"]) >= 4
    assert isinstance(cfg["workspace_name"], str) and cfg["workspace_name"].strip()


def test_state_example_is_valid_json():
    json.loads((SRC / "state.example.json").read_text(encoding="utf-8"))


# ── Generator invariants ────────────────────────────────────────
@pytest.fixture(scope="module")
def generated():
    import generate_data as g
    cfg = g.load_config()
    topo, meta = g.build_topology(cfg)
    tele = g.build_telemetry(cfg, topo, meta)
    return cfg, topo, meta, tele


def test_culprit_gate_exists(generated):
    cfg, topo, meta, _ = generated
    assert cfg["culprit_gate"] in set(topo["dim_gates"]["gate_id"])
    assert len(meta["culprit_zones"]) >= 1, "culprit gate must serve a zone"


def test_topology_keys_not_null(generated):
    _, topo, _, _ = generated
    for name, df in topo.items():
        assert not df.empty, f"{name} is empty"
        key = df.columns[0]
        assert df[key].notna().all(), f"{name}.{key} has nulls"


def test_vip_session_in_culprit_zone(generated):
    _, topo, meta, _ = generated
    ses = topo["dim_sessions"]; cust = topo["dim_customers"]
    vip_ids = set(cust[cust["vip_flag"]]["customer_id"])
    culprit_zones = set(meta["culprit_zones"])
    hit = ses[(ses["zone_id"].isin(culprit_zones)) & (ses["sponsor_id"].isin(vip_ids))]
    assert len(hit) >= 1, "at least one VIP-sponsored session must sit in the culprit zone for impact demo"


def test_congestion_event_present(generated):
    _, _, meta, tele = generated
    q = tele["telemetry_queue"]
    culprit_q = q[q["gate_id"] == meta["culprit"]]
    assert culprit_q["wait_time_s"].max() > 600, "congestion wait-time spike missing on culprit gate"
    others = q[q["gate_id"] != meta["culprit"]]
    assert others["wait_time_s"].max() < 600, "non-culprit gates should stay below the congestion threshold"


def test_zone_saturation_on_culprit_zones(generated):
    _, _, meta, tele = generated
    kpi = tele["telemetry_kpi"]
    occ = kpi[(kpi["kpi_name"] == "occupancy_pct") & (kpi["zone_id"].isin(meta["culprit_zones"]))]
    assert occ["value"].max() > 90, "culprit zone must saturate (occupancy > 90) during the peak"
    dens = kpi[(kpi["kpi_name"] == "density_index") & (kpi["zone_id"].isin(meta["culprit_zones"]))]
    assert dens["value"].max() > 4, "culprit zone must show a crowd-density spike"


def test_congestion_alarm_raised(generated):
    _, _, meta, tele = generated
    alarms = tele["alarms"]
    assert ((alarms["gate_id"] == meta["culprit"]) &
            (alarms["alarm_type"] == "CONGESTION")).any(), "missing CONGESTION alarm"


# ── Regression guards (bugs hit during earlier builds — keep them fixed) ──
def test_ontology_name_props_present():
    """Customer/Session/Zone expose `name`; Customer has vip_flag (used in impact + fewshots)."""
    import deploy_ontology as o
    props = {ent: {c for c, _t in cols} for ent, _tbl, _keys, cols in o.ENTITIES}
    assert "name" in props["Customer"] and "customer_name" not in props["Customer"]
    assert "name" in props["Session"]
    assert "name" in props["Zone"], "Zone.name is used by the Data Agent fewshots"
    assert "vip_flag" in props["Customer"]


def test_operations_agent_instructions_minimal():
    """Operations Agent INSTRUCTIONS must hold ONLY the two rule-generation sections."""
    import deploy_operations_agent as oa
    headers = re.findall(r"\*\*\*[^*]+\*\*\*", oa.INSTRUCTIONS)
    assert oa.INSTRUCTIONS.count("*** Operational Instructions ***") == 1
    assert oa.INSTRUCTIONS.count("*** Semantic Instructions ***") == 1
    assert len(headers) == 2, f"INSTRUCTIONS must have exactly 2 sections, found {headers}"
    assert re.search(r"reroute|redirect|open|hold|steward|overflow|lane", oa.GOALS, re.I), "GOALS should carry remediation guidance"


def test_data_agent_fewshots_use_valid_labels():
    """Every node/edge label in the Data Agent fewshots must exist in the ontology model."""
    import deploy_ontology as o
    import deploy_data_agent as da
    entity_names = {ent for ent, *_ in o.ENTITIES}
    rel_names = {rel for rel, *_ in o.RELATIONSHIPS}
    for question, gql in da.FEWSHOTS:
        for label in re.findall(r"\(\s*\w+\s*:\s*(\w+)", gql):
            assert label in entity_names, f"fewshot '{question}' uses unknown node label :{label}"
        for label in re.findall(r"\[\s*:\s*(\w+)", gql):
            assert label in rel_names, f"fewshot '{question}' uses unknown edge label :{label}"
