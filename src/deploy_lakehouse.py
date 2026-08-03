#!/usr/bin/env python3
"""
Deploy the Network topology Lakehouse: create the item + upload topology CSVs to
OneLake Files/raw/. Delta tables are created afterwards by deploy_setup_notebook.py.

Only TOPOLOGY tables go here (dim_*, fact_tickets). Telemetry goes to the Eventhouse.

OneLake upload uses a single reusable http.client.HTTPSConnection (3-step DFS:
PUT create -> PATCH append -> PATCH flush) — requests/urllib3 hang on OneLake DFS.
"""
import os, sys, json, subprocess, http.client
from platform_env import bootstrap
bootstrap()

from pathlib import Path
import requests
from platform_env import AZ_NEEDS_SHELL
from helpers import (load_config, load_state, save_state, get_fabric_token,
                     fabric_headers, poll_operation, find_item, print_step)

SRC = Path(__file__).parent
RAW = SRC.parent / "data" / "raw"
ONELAKE_HOST = "onelake.dfs.fabric.microsoft.com"


def storage_token() -> str:
    out = subprocess.check_output(
        ["az", "account", "get-access-token", "--resource", "https://storage.azure.com",
         "--query", "accessToken", "-o", "tsv"], shell=AZ_NEEDS_SHELL)
    return out.decode().strip()


def upload_files(ws_id, lh_id, token, names):
    conn = http.client.HTTPSConnection(ONELAKE_HOST, timeout=120)
    hdr = {"Authorization": f"Bearer {token}"}
    try:
        for name in names:
            data = (RAW / f"{name}.csv").read_bytes()
            base = f"/{ws_id}/{lh_id}/Files/raw/{name}.csv"
            # 1) create file
            conn.request("PUT", base + "?resource=file", headers=hdr); conn.getresponse().read()
            # 2) append
            h2 = dict(hdr); h2["Content-Type"] = "application/octet-stream"
            conn.request("PATCH", base + "?action=append&position=0", body=data, headers=h2)
            conn.getresponse().read()
            # 3) flush
            conn.request("PATCH", base + f"?action=flush&position={len(data)}", headers=hdr)
            r = conn.getresponse(); r.read()
            print(f"   uploaded raw/{name}.csv ({len(data)} bytes) [{r.status}]")
    finally:
        conn.close()


def main():
    cfg = load_config(); state = load_state()
    api = cfg["fabric_api_base"]; ws = state["workspace_id"]; name = cfg["lakehouse_name"]
    token = get_fabric_token(); h = fabric_headers(token)

    print_step(1, 3, f"Create or find Lakehouse '{name}'")
    lh_id = None
    try:
        lh_id = find_item(token, api, ws, name, "Lakehouse")["id"]
        print(f"   reusing: {lh_id}")
    except RuntimeError:
        r = requests.post(f"{api}/workspaces/{ws}/items", headers=h,
                          json={"displayName": name, "type": "Lakehouse",
                                "description": "Network topology (NonTimeSeries)"}, timeout=60)
        if r.status_code in (200, 201):
            lh_id = r.json()["id"]
        elif r.status_code == 202:
            op = r.headers.get("x-ms-operation-id")
            if op: poll_operation(token, api, op)
            lh_id = find_item(token, api, ws, name, "Lakehouse")["id"]
        else:
            raise RuntimeError(f"Create Lakehouse failed ({r.status_code}): {r.text[:300]}")
        print(f"   created: {lh_id}")

    print_step(2, 3, "Upload topology CSVs to OneLake Files/raw/")
    # topology = every generated CSV that is NOT a telemetry (Eventhouse/KQL) table
    telemetry = {t["name"] for t in cfg["kql_tables"].values()}
    names = sorted(p.stem for p in RAW.glob("*.csv") if p.stem not in telemetry)
    upload_files(ws, lh_id, storage_token(), names)

    print_step(3, 3, "Persist state (+ SQL endpoint)")
    det = requests.get(f"{api}/workspaces/{ws}/lakehouses/{lh_id}", headers=h, timeout=60).json()
    sql = det.get("properties", {}).get("sqlEndpointProperties", {}).get("connectionString")
    state["lakehouse_id"] = lh_id
    if sql: state["lakehouse_sql_endpoint"] = sql
    save_state(state)
    print(f"   lakehouse_id = {lh_id}")
    print("\nOK. Next: deploy_setup_notebook.py to create Delta tables from the CSVs.")


if __name__ == "__main__":
    main()
