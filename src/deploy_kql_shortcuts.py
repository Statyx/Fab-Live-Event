#!/usr/bin/env python3
"""
Expose the Eventhouse/KQL telemetry to the Lakehouse (for Direct Lake) WITHOUT a gold notebook.

Two steps, both scriptable:
  1. Turn on OneLake availability for each telemetry table via the Kusto MIRRORING POLICY
     (`.alter-merge table <T> policy mirroring dataformat=parquet with (IsEnabled=true,
     TargetLatencyInMinutes=5)`). This mirrors the KQL table to Delta in OneLake, read-only.
  2. Create a OneLake shortcut in the Lakehouse (Tables/<table>) pointing at the KQL DB's Delta
     path, so a Direct Lake semantic model / the SQL endpoint can read the live telemetry.

After this, the semantic model can be Direct Lake over BOTH the topology Delta tables and the
telemetry shortcuts. Mirroring latency is ~5 min (TargetLatencyInMinutes=5); run
`.show table <T> mirroring operations` — Latency 00:00:00 means fully mirrored.
"""
import sys, time
from platform_env import bootstrap
bootstrap()

import requests
from helpers import (load_config, load_state, save_state, get_fabric_token,
                     fabric_headers, get_kusto_token, kusto_mgmt, print_step)

# Telemetry tables to expose to the Lakehouse for Direct Lake reporting.
SHORTCUT_TABLES = ["telemetry_kpi", "telemetry_queue"]


def enable_mirroring(quri, ktok, db, table, latency=5):
    """Turn on OneLake availability for a KQL table (mirror to Delta in OneLake)."""
    cmd = (f".alter-merge table {table} policy mirroring "
           f"dataformat=parquet with (IsEnabled=true, TargetLatencyInMinutes={latency})")
    kusto_mgmt(quri, ktok, db, cmd)


def create_shortcut(api, ws, lh_id, headers, name, target_item_id, target_path):
    """Create a OneLake shortcut in the Lakehouse Tables/ pointing at a KQL Delta table."""
    body = {"path": "Tables", "name": name,
            "target": {"oneLake": {"workspaceId": ws, "itemId": target_item_id, "path": target_path}}}
    r = requests.post(f"{api}/workspaces/{ws}/items/{lh_id}/shortcuts",
                      headers=headers, json=body, timeout=60)
    if r.status_code in (200, 201):
        return "created"
    if r.status_code == 409:
        return "exists"
    raise RuntimeError(f"shortcut {name} failed ({r.status_code}): {r.text[:300]}")


def main():
    cfg = load_config(); state = load_state()
    api = cfg["fabric_api_base"]; ws = state["workspace_id"]; lh_id = state["lakehouse_id"]
    db = cfg["eventhouse_name"]; quri = state["query_service_uri"]
    kql_db_id = state["kql_database_id"]
    token = get_fabric_token(); h = fabric_headers(token)

    print_step(1, 3, "Enable OneLake availability (mirroring policy) on telemetry tables")
    ktok = get_kusto_token(quri)
    for t in SHORTCUT_TABLES:
        for attempt in range(1, 5):
            try:
                enable_mirroring(quri, ktok, db, t)
                print(f"   mirroring ON: {t}")
                break
            except Exception as e:
                if attempt < 4:
                    print(f"      (transient, retry {attempt}/3 in 6s)"); time.sleep(6)
                else:
                    raise

    print_step(2, 3, "Create OneLake shortcuts in the Lakehouse (Tables/<table>)")
    # The KQL DB mirrors its tables under its own OneLake item at Tables/<table>.
    made = {}
    for t in SHORTCUT_TABLES:
        try:
            status = create_shortcut(api, ws, lh_id, h, t, kql_db_id, f"Tables/{t}")
        except RuntimeError as e:
            # fall back to the eventhouse item id if the KQL DB id path is not accepted
            if state.get("eventhouse_id"):
                status = create_shortcut(api, ws, lh_id, h, t, state["eventhouse_id"], f"Tables/{t}")
            else:
                raise
        made[t] = status
        print(f"   shortcut {t}: {status}")

    print_step(3, 3, "Persist state")
    state["kql_shortcuts"] = made; save_state(state)
    print("   shortcuts:", made)
    print("\nOK. Telemetry mirrored to OneLake + shortcut in the Lakehouse.")
    print("   Direct Lake can now read telemetry_kpi + telemetry_queue alongside the topology tables.")
    print("   NOTE: mirroring latency ~5 min — wait until the shortcut tables show rows before")
    print("   refreshing the semantic model (or run deploy_semantic_model.py a few minutes later).")


if __name__ == "__main__":
    main()
