#!/usr/bin/env python3
"""
Deploy the Fabric workspace (config `workspace_name`) and assign it to the capacity.
Idempotent: finds an existing workspace by name; otherwise creates + assigns capacity.
Saves workspace_id to state.json.
"""
import sys
# ── cross-platform PATH self-heal (venv activation can wipe it; az runs via subprocess) ──
from platform_env import bootstrap
bootstrap()

import requests
from helpers import (load_config, load_state, save_state, get_fabric_token,
                     fabric_headers, poll_operation, print_step)


def main():
    cfg = load_config(); state = load_state()
    api = cfg["fabric_api_base"]; name = cfg["workspace_name"]; cap = cfg["capacity_id"]
    token = get_fabric_token(); h = fabric_headers(token)

    print_step(1, 3, f"Find or create workspace '{name}'")
    ws_id = None
    r = requests.get(f"{api}/workspaces", headers=h, timeout=60)
    r.raise_for_status()
    for w in r.json().get("value", []):
        if w.get("displayName") == name:
            ws_id = w["id"]; print(f"   reusing: {ws_id}"); break
    if not ws_id:
        cr = requests.post(f"{api}/workspaces", headers=h,
                           json={"displayName": name,
                                 "description": "NOA demo — Fabric Graph + Ontology + Operations Agent"},
                           timeout=60)
        if cr.status_code in (200, 201):
            ws_id = cr.json()["id"]
        elif cr.status_code == 202:
            op = cr.headers.get("x-ms-operation-id")
            if op: poll_operation(token, api, op)
            r2 = requests.get(f"{api}/workspaces", headers=h, timeout=60)
            ws_id = next(w["id"] for w in r2.json()["value"] if w["displayName"] == name)
        else:
            raise RuntimeError(f"Create workspace failed ({cr.status_code}): {cr.text[:400]}")
        print(f"   created: {ws_id}")

    print_step(2, 3, "Assign capacity")
    ac = requests.post(f"{api}/workspaces/{ws_id}/assignToCapacity", headers=h,
                       json={"capacityId": cap}, timeout=60)
    if ac.status_code in (200, 202):
        print(f"   capacity assigned ({cap[:8]}…)")
    elif ac.status_code == 400 and "already" in ac.text.lower():
        print("   capacity already assigned")
    else:
        print(f"   assignToCapacity -> {ac.status_code}: {ac.text[:200]}")

    print_step(3, 3, "Persist state")
    state["workspace_id"] = ws_id
    save_state(state)
    print(f"   workspace_id = {ws_id}")
    print("\nOK.")


if __name__ == "__main__":
    main()
