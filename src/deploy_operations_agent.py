#!/usr/bin/env python3
"""
Create the Fabric Operations Agent 'Event_Operations_Agent'.

Per the rti-kusto-agent brain (operations_agent.md): the Operations Agent is a real
Fabric item (endpoint /OperationsAgents, F2+) that monitors the real-time KQL database
and can alert via Teams. This script:
  1. Creates the OperationsAgents item.
  2. Pushes Configurations.json (goals + instructions + shouldRun=false).
The Knowledge Source (KQL DB), Teams action and schedule are added in the UI (cannot be
done via API). shouldRun stays FALSE so the agent is NOT scheduled/active until you flip it.
"""
import os, sys, winreg
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
                     fabric_headers, poll_operation, b64encode_json, print_step)

ALERT_RECIPIENT = "alerts@example.com"  # set to your UPN / Teams recipient (bindings are wired in the UI)

GOALS = """You are the Event Operations Agent for a Contoso Events control room. You continuously
monitor the live gate-queue and zone telemetry in the Eventhouse and raise an alert to the on-duty
operations lead the moment a gate or zone breaches a threshold, naming the affected gate or zone and
the metric that breached, so the team can act before the attendee experience or safety degrades.
Whenever you raise an alert, also state the single most likely remediation the operations lead should
take next: for a congestion at a gate, recommend opening additional lanes and redirecting flow to a
nearby gate; for a saturated zone, high crowd density or low comfort, recommend holding entry to the
zone, deploying stewards and opening an overflow area."""

INSTRUCTIONS = """*** Operational Instructions ***
1. Alert me when a gate has a congestion.
2. Alert me when a zone is saturated.
3. Alert me when a zone has high crowd density.
4. Alert me when a zone has low comfort.

*** Semantic Instructions ***
1. The "telemetry_queue" table holds gate queue telemetry. Each record belongs to ONE gate,
   uniquely identified by the "gate_id" column. Use only "gate_id" as the entity identifier for this
   table; ignore the "zone_id" column for identity. A congestion is when "wait_time_s" is above 600.
2. The "telemetry_kpi" table holds zone performance telemetry in long format. Each record belongs to
   ONE zone, uniquely identified by the "zone_id" column. Use only "zone_id" as the entity identifier
   for this table; ignore the "gate_id" column for identity. The "kpi_name" column names the metric
   and the "value" column holds its number.
3. Saturation is the "value" where "kpi_name" is "occupancy_pct". A zone is saturated when it is above 90.
4. Crowd density is the "value" where "kpi_name" is "density_index". High crowd density is above 4.
5. Comfort is the "value" where "kpi_name" is "comfort_index". Low comfort is below 30.
6. Use the "timestamp" column to evaluate the most recent data."""


def find_agent(api, ws, headers, name):
    items = requests.get(f"{api}/workspaces/{ws}/items", headers=headers, timeout=60).json().get("value", [])
    for it in items:
        if it.get("type") in ("OperationsAgent", "OperationsAgents") and it.get("displayName") == name:
            return it["id"]
    return None


def main():
    cfg = load_config(); state = load_state()
    api = cfg["fabric_api_base"]; ws = state["workspace_id"]; name = cfg["operations_agent_name"]
    token = get_fabric_token(); h = fabric_headers(token)

    print_step(1, 3, f"Create Operations Agent item '{name}'")
    aid = state.get("operations_agent_id") or find_agent(api, ws, h, name)
    if aid:
        print(f"   reusing: {aid}")
    else:
        r = requests.post(f"{api}/workspaces/{ws}/OperationsAgents", headers=h,
                          json={"displayName": name,
                                "description": "LEO real-time event monitor over EH_Event_Telemetry (Knowledge Source + Teams + schedule set in UI; not active yet)"},
                          timeout=60)
        if r.status_code in (200, 201):
            aid = r.json()["id"]
        elif r.status_code == 202:
            op = r.headers.get("x-ms-operation-id")
            if op: poll_operation(token, api, op)
            aid = find_agent(api, ws, h, name)
        else:
            raise RuntimeError(f"Create OperationsAgent failed ({r.status_code}): {r.text[:500]}")
        print(f"   created: {aid}")

    print_step(2, 3, "Push Configurations.json (goals + instructions; shouldRun=false)")
    # Keep INSTRUCTIONS minimal (Operational + Semantic only) — a third section destabilizes the
    # playbook generator. Persona/remediation live in GOALS. Raw API push zeroes the data source id
    # and drops the destination, so Knowledge Source + destination + rules are set in the UI.
    config = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/operationsAgents/definition/1.0.0/schema.json",
        "configuration": {
            "goals": GOALS,
            "instructions": INSTRUCTIONS,
            "dataSources": {},
            "actions": {},
        },
        "shouldRun": False,
    }
    body = {"definition": {"parts": [{
        "path": "Configurations.json",
        "payload": b64encode_json(config),
        "payloadType": "InlineBase64"}]}}
    r = requests.post(f"{api}/workspaces/{ws}/items/{aid}/updateDefinition",
                      headers=h, json=body, timeout=120)
    if r.status_code == 202:
        op = r.headers.get("x-ms-operation-id")
        if op: poll_operation(token, api, op)
    elif r.status_code not in (200, 201):
        raise RuntimeError(f"updateDefinition failed ({r.status_code}): {r.text[:500]}")
    print(f"   definition uploaded ({r.status_code})")

    print_step(3, 3, "Persist state")
    state["operations_agent_id"] = aid; save_state(state)
    print(f"   operations_agent_id = {aid}")
    print(f"\nOK. Operations Agent '{name}' deployed (NOT running).")
    print("   goals + instructions set via API (Eventhouse/KQL detection: gate congestion + zone saturation/density/comfort).")
    print("   In the Fabric UI, finish: add the Knowledge Source = Eventhouse KQL database")
    print("   'EventTelemetry' (tables telemetry_queue + telemetry_kpi), set the alert destination")
    print("   (Teams/email), Generate playbook, set a schedule, then enable it (shouldRun=true).")
    print("   (Raw API push zeroes the data source id and drops the destination, so the Knowledge")
    print("   Source + destination must be set in the UI. Impact/RCA/VIP stays on the Data Agent.)")


if __name__ == "__main__":
    main()
