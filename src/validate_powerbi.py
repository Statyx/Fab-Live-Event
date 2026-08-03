#!/usr/bin/env python3
"""
Validate the Power BI layer: run DAX against SM_Event_Analytics via the Power BI
executeQueries REST API. Confirms the Direct Lake model loads (topology + telemetry
shortcuts) and the key persona measures return values.
"""
import sys, subprocess, json
# ── cross-platform PATH self-heal (venv activation can wipe it; az runs via subprocess) ──
from path_utils import IS_WINDOWS, restore_path, configure_stdout
restore_path()
configure_stdout()

from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).parent))
from helpers import load_state, print_step

PBI = "https://api.powerbi.com/v1.0/myorg"


def pbi_token():
    out = subprocess.check_output(
        ["az", "account", "get-access-token", "--resource",
         "https://analysis.windows.net/powerbi/api", "--query", "accessToken", "-o", "tsv"],
        shell=IS_WINDOWS)
    return out.decode().strip()


def run_dax(ws, sm_id, tok, dax):
    r = requests.post(f"{PBI}/groups/{ws}/datasets/{sm_id}/executeQueries",
                      headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
                      json={"queries": [{"query": dax}], "serializerSettings": {"includeNulls": True}},
                      timeout=90)
    if r.status_code != 200:
        return None, f"{r.status_code}: {r.text[:200]}"
    rows = r.json()["results"][0]["tables"][0]["rows"]
    return rows, None


CHECKS = [
    ("Topology — zones/gates/sponsors",
     'EVALUATE ROW("Zones", [Total Zones], "Gates", [Total Gates], "Sponsors", [Total Sponsors], "VIP", [VIP Sponsors], "Sessions", [Total Sessions])'),
    ("BIM — surface/capacity/premium",
     'EVALUATE ROW("Surface m2", [Total Surface (m²)], "Capacity", [Total Capacity], "Premium Zones", [Premium Zones])'),
    ("Telemetry KPI (shortcut) — occupancy/attendance",
     'EVALUATE ROW("Peak Occ %", [Peak Occupancy %], "Peak Attendees", [Peak Attendees], "Saturated", [Saturated Zones (>90%)])'),
    ("Telemetry queue (shortcut) — waits/flow",
     'EVALUATE ROW("Peak Wait min", [Peak Wait (min)], "Entries", [Total Entries], "Congested Gates", [Gates in Congestion (>10 min)])'),
    ("Top congested gate",
     'EVALUATE TOPN(3, ADDCOLUMNS(VALUES(dim_gates[gate_id]), "Wait", [Peak Wait (min)]), [Wait], DESC)'),
]


def main():
    state = load_state()
    ws = state["workspace_id"]; sm_id = state["semantic_model_id"]
    tok = pbi_token()
    print_step(1, 1, f"Validating semantic model {sm_id}")
    ok = 0
    for label, dax in CHECKS:
        rows, err = run_dax(ws, sm_id, tok, dax)
        if err:
            print(f"   [FAIL] {label}\n          {err}")
        else:
            print(f"   [OK]   {label}: {json.dumps(rows, ensure_ascii=False)}")
            ok += 1
    print(f"\n{ok}/{len(CHECKS)} checks passed.")
    if ok < len(CHECKS):
        print("   NOTE: telemetry checks can fail until OneLake mirroring finishes (~5 min) and the")
        print("   Lakehouse SQL endpoint syncs the shortcut. Re-run after a few minutes.")


if __name__ == "__main__":
    main()
