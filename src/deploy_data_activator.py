#!/usr/bin/env python3
"""
Create the Data Activator (Reflex) item RX_Event_Alerts.

Per the data-activator-agent brain guidance, Reflex rule definitions (the AttributeTrigger
steps + action reference shapes) are fragile and should be preserved from a working readback.
No working template is available here, and hand-authoring blind reliably 400s — so this script
creates the Reflex ITEM via the /reflexes endpoint (reliable) and the RULE is authored in the
Fabric UI (the supported UX). The alert is therefore NOT active until you create + start the rule.

Intended rule (author in UI, leave STOPPED until ready):
  Source : KQL  -> EH_Event_Telemetry / telemetry_queue  (return all rows; the rule filters)
  Trigger: AttributeTrigger, detector NumberBecomes  wait_time_s > 600
  Filter : (optional) by gate_id
  Action : Email / Teams "Congestion detected at gate {gate_id}"
  State  : shouldRun = false (stopped) until you flip it on for the demo
"""
import os, sys
from platform_env import bootstrap
bootstrap()

import requests
from helpers import (load_config, load_state, save_state, get_fabric_token,
                     fabric_headers, poll_operation, print_step)


def find_reflex(api, ws, headers, name):
    items = requests.get(f"{api}/workspaces/{ws}/items", headers=headers, timeout=60).json().get("value", [])
    for it in items:
        if it.get("type") == "Reflex" and it.get("displayName") == name:
            return it["id"]
    return None


def main():
    cfg = load_config(); state = load_state()
    api = cfg["fabric_api_base"]; ws = state["workspace_id"]; name = cfg["data_activator_name"]
    token = get_fabric_token(); h = fabric_headers(token)

    print_step(1, 2, f"Create Reflex item '{name}' (rule authored in UI; alert NOT active)")
    rid = state.get("reflex_id") or find_reflex(api, ws, h, name)
    if rid:
        print(f"   reusing: {rid}")
    else:
        r = requests.post(f"{api}/workspaces/{ws}/reflexes", headers=h,
                          json={"displayName": name,
                                "description": "LEO event alerts — gate congestion / zone saturation thresholds (rule authored in UI; not active yet)"},
                          timeout=60)
        if r.status_code in (200, 201):
            rid = r.json()["id"]
        elif r.status_code == 202:
            op = r.headers.get("x-ms-operation-id")
            if op: poll_operation(token, api, op)
            rid = find_reflex(api, ws, h, name)
        else:
            raise RuntimeError(f"Create Reflex failed ({r.status_code}): {r.text[:400]}")
        print(f"   created: {rid}")

    print_step(2, 2, "Persist state")
    state["reflex_id"] = rid; save_state(state)
    print(f"   reflex_id = {rid}")
    print("\nOK. Reflex item ready. Author the rule in the Fabric UI (keep it STOPPED):")
    print("   Source KQL telemetry_queue -> AttributeTrigger wait_time_s NumberBecomes > 600 -> Email/Teams action.")


if __name__ == "__main__":
    main()
