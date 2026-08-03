#!/usr/bin/env python3
"""
Trigger a fast RefreshGraph on the Network Graph Model (no definition rebuild).

WHEN TO RUN: after the **topology** (Lakehouse) data changes — e.g. you regenerated
a denser dataset and re-ran deploy_lakehouse. The graph is built from the static
Lakehouse tables, so new/changed rows are only picked up by a RefreshGraph (full
re-ingest). deploy_graph.py also refreshes, but it rebuilds the whole definition;
this script just re-ingests the existing graph and is much faster.

WHEN NOT TO RUN: after inject_event.py. That injects **telemetry** into the
Eventhouse, and the Graph Model is topology-only — telemetry is queried live via the
ontology's TimeSeries bindings / KQL, never ingested into the graph. So a live storm
injection needs NO graph refresh.

    python refresh_graph.py
"""
import sys
from platform_env import bootstrap
bootstrap()

import time
import requests
from helpers import get_fabric_token, fabric_headers, load_config, load_state
from deploy_graph import find_graph_model


def refresh_graph(api, ws, headers, graph_id, timeout_polls=80):
    """Trigger RefreshGraph and poll to completion. Returns the final status string."""
    jr = requests.post(f"{api}/workspaces/{ws}/items/{graph_id}/jobs/instances?jobType=RefreshGraph",
                       headers=headers, json={}, timeout=60)
    if jr.status_code not in (200, 201, 202):
        raise RuntimeError(f"RefreshGraph failed to start ({jr.status_code}): {jr.text[:400]}")
    loc = jr.headers.get("Location")
    if jr.status_code != 202 or not loc:
        return "Started"
    for _ in range(timeout_polls):
        time.sleep(5)
        j = requests.get(loc, headers=headers).json()
        status = j.get("status")
        print(f"   refresh: {status}")
        if status in ("Completed", "Failed", "Cancelled", "Deduped"):
            if status == "Failed":
                print("   failure:", j.get("failureReason"))
            return status
    return "Timeout"


def main():
    cfg = load_config(); state = load_state()
    api = cfg["fabric_api_base"]; ws = state["workspace_id"]
    substr = cfg["ontology_name"] + "_graph"
    headers = fabric_headers(get_fabric_token())

    print("Locating Graph Model item...")
    gid = state.get("graph_model_id")
    if not gid:
        gid, gname = find_graph_model(api, ws, headers, substr)
        print(f"   {gname} ({gid})")
    else:
        print(f"   {gid}")

    print("Triggering RefreshGraph (re-ingest topology)...")
    status = refresh_graph(api, ws, headers, gid)
    print(f"\nDone. Final status: {status}")


if __name__ == "__main__":
    main()
