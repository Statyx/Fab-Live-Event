#!/usr/bin/env python3
"""
Create the Eventhouse + KQL Database + telemetry KQL tables (streaming-ingestion on).
The KQL database name == the eventhouse name (auto-created). Saves eventhouse_id,
kql_database_id, query_service_uri to state.
"""
import os, sys, winreg, time
def _restore_path():
    parts = []
    for root, sub in [(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                      (winreg.HKEY_CURRENT_USER, "Environment")]:
        try:
            k = winreg.OpenKey(root, sub); v, _ = winreg.QueryValueEx(k, "Path")
            parts.append(os.path.expandvars(v)); winreg.CloseKey(k)
        except Exception: pass
    if parts: os.environ["PATH"] = ";".join(parts) + ";" + os.environ.get("PATH", "")
_restore_path()
if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")

import requests
from helpers import (load_config, load_state, save_state, get_fabric_token,
                     get_kusto_token, fabric_headers, create_fabric_item,
                     kusto_mgmt, print_step)


def wait_for_kql_db(token, api, ws, eh_name, tries=20):
    h = fabric_headers(token)
    for i in range(tries):
        r = requests.get(f"{api}/workspaces/{ws}/items?type=KQLDatabase", headers=h, timeout=60)
        r.raise_for_status()
        for db in r.json().get("value", []):
            if db["displayName"] == eh_name:
                return db
        print(f"   waiting for KQL DB ({i+1}/{tries})...")
        time.sleep(10)
    raise RuntimeError("KQL Database not provisioned")


def main():
    cfg = load_config(); state = load_state()
    api = cfg["fabric_api_base"]; ws = state["workspace_id"]; eh_name = cfg["eventhouse_name"]
    token = get_fabric_token()

    print_step(1, 4, f"Create Eventhouse '{eh_name}'")
    if state.get("eventhouse_id"):
        print(f"   reusing: {state['eventhouse_id']}")
    else:
        eh = create_fabric_item(token, api, ws, eh_name, "Eventhouse", "Network telemetry (TimeSeries)")
        state["eventhouse_id"] = eh["id"]; save_state(state)
        print(f"   created: {eh['id']}")

    print_step(2, 4, "Wait for KQL Database + query URI")
    db = wait_for_kql_db(token, api, ws, eh_name)
    state["kql_database_id"] = db["id"]
    eh_det = requests.get(f"{api}/workspaces/{ws}/eventhouses/{state['eventhouse_id']}", headers=fabric_headers(token), timeout=60).json()
    quri = eh_det["properties"]["queryServiceUri"]
    state["query_service_uri"] = quri; save_state(state)
    print(f"   KQL DB {db['id']} · {quri}")

    print_step(3, 4, "Create KQL tables")
    ktok = get_kusto_token(quri)
    time.sleep(15)
    for _, t in cfg["kql_tables"].items():
        cols = ", ".join(f"{c['name']}:{c['type']}" for c in t["columns"])
        kusto_mgmt(quri, ktok, eh_name, f".create-merge table {t['name']} ({cols})")
        print(f"   table {t['name']} ready")

    print_step(4, 4, "Enable streaming ingestion")
    for _, t in cfg["kql_tables"].items():
        try:
            kusto_mgmt(quri, ktok, eh_name, f".alter table {t['name']} policy streamingingestion enable")
            print(f"   streaming on {t['name']}")
        except Exception as e:
            print(f"   ! {t['name']}: {e}")
    print("\nOK. Next: preload_telemetry.py")


if __name__ == "__main__":
    main()
