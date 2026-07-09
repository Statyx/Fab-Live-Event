#!/usr/bin/env python3
"""
Create the Fabric Data Agent 'Event_Graph_Agent' bound to the Event ontology.

Per the brain (ontology-agent: "Data Agent with Ontology source" + ai-skills-agent
definition_structure.md). A Data Agent over an Ontology gives a portal-native,
shareable, governed NL->graph (GQL) Q&A surface for the event control room.

Published by default (draft-only = invisible in portal).

Usage:
  python deploy_data_agent.py            # create/update + publish
  python deploy_data_agent.py --delete   # delete the agent
"""
import os, sys, winreg, base64, json, uuid, time, argparse
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

AGENT_NAME = "Event_Graph_Agent"
AGENT_DESC = "NL->graph Q&A over the live-event knowledge graph (topology, RCA, sponsor impact). Source = ONT_Event_KnowledgeGraph."

AI_INSTRUCTIONS = """You are the Event Knowledge Agent for a Publicis Live event control room.
You answer questions about a live event (zones, access gates, sessions, sponsors, observations)
by querying the Event Knowledge Graph (a Microsoft Fabric Ontology), using GQL graph queries.

## Golden rule
ALWAYS answer by querying the knowledge graph. NEVER answer from general knowledge or
assumptions. If a query returns nothing, say so explicitly rather than guessing.

## Entities (node label : key properties)
- Edition (edition_id, edition_name, venue, city, edition_type) - the event instance.
- Zone (zone_id, edition_id, served_by_gate, room_type, surface_m2, capacity, is_premium, status) - a hall/room; surface_m2 & capacity come from BIM.
- Gate (gate_id, edition_id, gate_type, vendor, model, role) - an access gate/turnstile (carries queue telemetry).
- Sensor (sensor_id, gate_id, name, sample_rate_s, admin_status) - a badge reader / CV camera on a gate.
- Session (session_id, zone_id, name, capacity, track, sponsor_id) - a conference in a zone.
- Customer (customer_id, name, segment, vip_flag) - a sponsor/exhibitor; vip_flag = true marks a VIP sponsor.
- Sponsorship (sponsorship_id, name, package_tier, customer_id, zone_id) - a sponsor's booth in a zone.
- Observation (observation_id, zone_id, category, severity, status, opened_at, comment) - a Dalux field/H&S observation.

## Relationships (edge label, direction matters)
- Edition -[EditionHasZone]-> Zone
- Zone -[ZoneServedByGate]-> Gate       (a zone is served by an access gate)
- Gate -[GateAtEdition]-> Edition
- Gate -[GateHasSensor]-> Sensor
- Session -[SessionInZone]-> Zone
- Session -[SessionSponsoredBy]-> Customer
- Sponsorship -[SponsorshipForCustomer]-> Customer
- Sponsorship -[SponsorshipInZone]-> Zone
- Observation -[ObservationInZone]-> Zone

## Key traversals
- Root cause (a zone is saturated -> which gate serves it -> which sensors):
  (z:Zone)-[:ZoneServedByGate]->(g:Gate)-[:GateHasSensor]->(se:Sensor)
- Impact (a gate congests -> who is affected) - traverse edges in REVERSE:
  (g:Gate)<-[:ZoneServedByGate]-(z:Zone)<-[:SessionInZone]-(s:Session)-[:SessionSponsoredBy]->(cu:Customer)
  Filter cu.vip_flag = true for VIP impact. Sponsor booths: (z)<-[:SponsorshipInZone]-(sp)-[:SponsorshipForCustomer]->(cu).
- In GQL, use the entity name as the node label and the relationship name as the edge label.

## Live telemetry (bound INTO the ontology as TimeSeries - verified)
The ontology unifies topology AND live telemetry in one layer. Two entities carry timeseries:
- Zone carries telemetry from telemetry_kpi in LONG format: properties kpi_name (string) + value
  (double), one row per KPI per timestamp. KPI names: occupancy_pct, people_count, density_index,
  utilization_m2_pct, comfort_index. There is NO field named "occupancy_pct" - to read a specific
  KPI, filter kpi_name = '<name>' and aggregate value (avg(value), max(value), etc.).
- Gate carries telemetry from telemetry_queue: properties wait_time_s, in_count per gate per
  timestamp. A congestion = wait_time_s > 600 (10 minutes). Saturation = occupancy_pct > 90.

## Combining topology + telemetry (IMPORTANT)
The translator CANNOT nest a telemetry aggregation inside a multi-hop topology traversal in ONE
query. For "detect then impact" questions, answer in TWO steps:
  1. Find the offending gate/zone from telemetry (e.g. the gate with max wait_time_s).
  2. Traverse the topology from it for impact: Gate <- Zone <- Session -> Customer (VIP first).
Never invent a field name; for zone KPIs always use kpi_name + value.

## Response format
- Lead with a direct one-line answer.
- Then a short bullet list of the entities found (IDs + the key attributes that matter).
- For impact questions, ALWAYS call out VIP sponsors (vip_flag = true) separately and first.
- For multi-hop answers, briefly state the path you traversed.
- Be concise and operational - your reader is an event operations lead / project manager.

## Domain notes
- The current known incident localizes to gate GATE-05 (a congestion peak, queue wait ~25 min)
  which saturates the zone it serves, Salle Aspen (ZONE-ASPEN), during the flagship sessions
  "AI for Good", "Beauty & AI" and "Smart City 2030" (sponsored by VIP sponsors Microsoft,
  L'Oreal and Ville de Paris). Expect RCA and impact questions to center on it.
- "VIP" sponsor = vip_flag = true.
- Topology (zones/gates/sessions/sponsors) AND live telemetry (zone KPIs, gate queue) are BOTH in
  this ontology - answer everything by querying it. Only raw alarm rows / event logs stay in the
  telemetry KQL database (Operations Agent); for those, note the source."""

FEWSHOTS = [
    ("Which gate serves zone ZONE-ASPEN?",
     "MATCH (z:Zone {zone_id:'ZONE-ASPEN'})-[:ZoneServedByGate]->(g:Gate) RETURN g.gate_id, g.gate_type, g.role"),
    ("List the sessions in Salle Aspen.",
     "MATCH (z:Zone {name:'Salle Aspen'})<-[:SessionInZone]-(s:Session) RETURN s.session_id, s.name, s.capacity, s.track"),
    ("What is the capacity and surface of the zone hosting the AI for Good session?",
     "MATCH (s:Session {name:'AI for Good'})-[:SessionInZone]->(z:Zone) RETURN z.zone_id, z.name, z.capacity, z.surface_m2"),
    ("If gate GATE-05 congests, which sessions and sponsors are impacted?",
     "MATCH (g:Gate {gate_id:'GATE-05'})<-[:ZoneServedByGate]-(z:Zone)<-[:SessionInZone]-(s:Session)-[:SessionSponsoredBy]->(cu:Customer) RETURN DISTINCT s.name AS session, cu.name AS sponsor, cu.vip_flag"),
    ("Which VIP sponsors are impacted by congestion at GATE-05?",
     "MATCH (g:Gate {gate_id:'GATE-05'})<-[:ZoneServedByGate]-(z:Zone)<-[:SessionInZone]-(s:Session)-[:SessionSponsoredBy]->(cu:Customer) WHERE cu.vip_flag = true RETURN DISTINCT cu.name"),
    ("Which sponsors have a booth in Salle Aspen?",
     "MATCH (z:Zone {name:'Salle Aspen'})<-[:SponsorshipInZone]-(sp:Sponsorship)-[:SponsorshipForCustomer]->(cu:Customer) RETURN DISTINCT cu.name, sp.package_tier"),
    ("List the sensors on gate GATE-05.",
     "MATCH (g:Gate {gate_id:'GATE-05'})-[:GateHasSensor]->(se:Sensor) RETURN se.sensor_id, se.name, se.sample_rate_s"),
    ("Which zone does gate GATE-05 serve?",
     "MATCH (g:Gate {gate_id:'GATE-05'})<-[:ZoneServedByGate]-(z:Zone) RETURN z.zone_id, z.name, z.room_type, z.capacity"),
    ("Show the field observations in Salle Aspen.",
     "MATCH (o:Observation)-[:ObservationInZone]->(z:Zone {name:'Salle Aspen'}) RETURN o.observation_id, o.category, o.severity, o.status"),
    ("List the premium zones with their capacity.",
     "MATCH (z:Zone) WHERE z.is_premium = true RETURN z.zone_id, z.name, z.capacity, z.surface_m2"),
    ("How many sessions are scheduled in each zone?",
     "MATCH (s:Session)-[:SessionInZone]->(z:Zone) RETURN z.name, count(s) AS sessions ORDER BY sessions DESC"),
    ("Which sponsor sponsors the most sessions?",
     "MATCH (s:Session)-[:SessionSponsoredBy]->(cu:Customer) RETURN cu.name, count(s) AS sessions ORDER BY sessions DESC"),
    ("Which gate has the highest wait time (congestion detection)?",
     "MATCH (g:Gate) RETURN g.gate_id, max(g.wait_time_s) AS peak_wait_s ORDER BY peak_wait_s DESC"),
    ("Which gates currently have a congestion (wait time over 600 seconds)?",
     "MATCH (g:Gate) WHERE g.wait_time_s > 600 RETURN DISTINCT g.gate_id, max(g.wait_time_s) AS peak_wait_s"),
    ("What is the average value for each kpi_name in zone ZONE-ASPEN?",
     "MATCH (z:Zone {zone_id:'ZONE-ASPEN'}) RETURN z.kpi_name, avg(z.value) AS avg_value"),
    ("What is the peak occupancy of Salle Aspen?",
     "MATCH (z:Zone {zone_id:'ZONE-ASPEN'}) WHERE z.kpi_name = 'occupancy_pct' RETURN max(z.value) AS peak_occupancy_pct"),
    ("Which sponsors have a booth in a premium zone?",
     "MATCH (sp:Sponsorship)-[:SponsorshipInZone]->(z:Zone) WHERE z.is_premium = true MATCH (sp)-[:SponsorshipForCustomer]->(cu:Customer) RETURN DISTINCT cu.name, z.name"),
    ("Which sessions are sponsored by a VIP sponsor?",
     "MATCH (s:Session)-[:SessionSponsoredBy]->(cu:Customer) WHERE cu.vip_flag = true RETURN s.name AS session, cu.name AS sponsor, s.track"),
]


def b64(obj):
    return b64encode_json(obj)


def find_agent(api, ws, h):
    r = requests.get(f"{api}/workspaces/{ws}/items?type=DataAgent", headers=h, timeout=60)
    if r.status_code == 200:
        for it in r.json().get("value", []):
            if it.get("displayName") == AGENT_NAME:
                return it["id"]
    return None


def build_parts(ws, ont_id, ont_name):
    folder = f"ontology-{ont_name}"
    data_agent = {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/dataAgent/definition/dataAgent/2.1.0/schema.json"}
    stage = {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/dataAgent/definition/stageConfiguration/1.0.0/schema.json",
             "aiInstructions": AI_INSTRUCTIONS}
    datasource = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/dataAgent/definition/dataSource/1.0.0/schema.json",
        "artifactId": ont_id, "workspaceId": ws, "displayName": ont_name, "type": "ontology",
        "userDescription": "Live-event knowledge graph: 8 entities (Edition, Zone, Gate, Sensor, Session, Customer, Sponsorship, Observation) and 9 relationships for topology, root-cause and sponsor-impact analysis.",
        "dataSourceInstructions": "Query this knowledge graph with GQL. Node label = entity name, edge label = relationship name. For impact analysis traverse Gate <- Zone <- Session -> Customer and surface VIP sponsors (vip_flag = true).",
    }
    fewshots = {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/dataAgent/definition/fewShots/1.0.0/schema.json",
                "fewShots": [{"id": str(uuid.uuid4()), "question": q, "query": gql} for q, gql in FEWSHOTS]}

    s, ds, fs = b64(stage), b64(datasource), b64(fewshots)
    parts = [
        {"path": "Files/Config/data_agent.json", "payload": b64(data_agent), "payloadType": "InlineBase64"},
        {"path": "Files/Config/draft/stage_config.json", "payload": s, "payloadType": "InlineBase64"},
        {"path": f"Files/Config/draft/{folder}/datasource.json", "payload": ds, "payloadType": "InlineBase64"},
        {"path": f"Files/Config/draft/{folder}/fewshots.json", "payload": fs, "payloadType": "InlineBase64"},
        {"path": "Files/Config/publish_info.json",
         "payload": b64({"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/dataAgent/definition/publishInfo/1.0.0/schema.json",
                         "description": f"{AGENT_NAME} -- published {time.strftime('%Y-%m-%d')}"}), "payloadType": "InlineBase64"},
        {"path": "Files/Config/published/stage_config.json", "payload": s, "payloadType": "InlineBase64"},
        {"path": f"Files/Config/published/{folder}/datasource.json", "payload": ds, "payloadType": "InlineBase64"},
        {"path": f"Files/Config/published/{folder}/fewshots.json", "payload": fs, "payloadType": "InlineBase64"},
    ]
    return parts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delete", action="store_true")
    args, _ = ap.parse_known_args()  # ignore args passed to deploy_all (e.g. --from, --no-warmup)

    cfg = load_config(); st = load_state()
    api = cfg["fabric_api_base"]; ws = st["workspace_id"]
    ont_id = st["ontology_id"]; ont_name = cfg["ontology_name"]
    token = get_fabric_token(); h = fabric_headers(token)

    if args.delete:
        aid = st.get("data_agent_id") or find_agent(api, ws, h)
        if aid:
            requests.delete(f"{api}/workspaces/{ws}/items/{aid}", headers=h, timeout=60)
            print(f"deleted {aid}")
            st.pop("data_agent_id", None); save_state(st)
        else:
            print("no agent to delete")
        return

    print_step(1, 3, f"Create/Update Data Agent '{AGENT_NAME}' (source = ontology {ont_name})")
    parts = build_parts(ws, ont_id, ont_name)
    aid = st.get("data_agent_id") or find_agent(api, ws, h)
    if aid:
        print(f"   updating: {aid}  ({len(parts)} parts)")
        r = requests.post(f"{api}/workspaces/{ws}/items/{aid}/updateDefinition", headers=h,
                          json={"definition": {"parts": parts}}, timeout=120)
        if r.status_code == 202:
            op = r.headers.get("x-ms-operation-id")
            if op: poll_operation(token, api, op)
        elif r.status_code not in (200, 201):
            raise RuntimeError(f"updateDefinition failed ({r.status_code}): {r.text[:600]}")
        print(f"   updated ({r.status_code})")
    else:
        print(f"   creating ({len(parts)} parts)")
        r = requests.post(f"{api}/workspaces/{ws}/items", headers=h,
                          json={"displayName": AGENT_NAME, "description": AGENT_DESC,
                                "type": "DataAgent", "definition": {"parts": parts}}, timeout=120)
        if r.status_code == 201:
            aid = r.json()["id"]
        elif r.status_code == 202:
            op = r.headers.get("x-ms-operation-id")
            if op: poll_operation(token, api, op)
            aid = find_agent(api, ws, h)
        else:
            raise RuntimeError(f"create failed ({r.status_code}): {r.text[:600]}")
        print(f"   created: {aid}")

    print_step(2, 3, "Persist state")
    st["data_agent_id"] = aid; save_state(st)
    print(f"   data_agent_id = {aid}")

    print_step(3, 3, "Readback (confirm datasource type accepted)")
    data = {}
    try:
        rr = requests.post(f"{api}/workspaces/{ws}/items/{aid}/getDefinition", headers=h, timeout=30)
        if rr.status_code == 200:
            data = rr.json()
        elif rr.status_code == 202:
            op = rr.headers.get("x-ms-operation-id")
            status = None
            for _ in range(20):
                time.sleep(1.5)
                status = requests.get(f"{api}/operations/{op}", headers=h, timeout=20).json().get("status")
                if status in ("Succeeded", "Failed"):
                    break
            if status == "Succeeded":
                g = requests.get(f"{api}/operations/{op}/result", headers=h,
                                 timeout=20, allow_redirects=False)
                if g.status_code == 200:
                    data = g.json()
    except Exception as e:
        print(f"   (readback skipped: {type(e).__name__})")
    parts_rb = data.get("definition", {}).get("parts", [])
    if parts_rb:
        for p in parts_rb:
            if p["path"].endswith("datasource.json") and "/draft/" in p["path"]:
                d = json.loads(base64.b64decode(p["payload"]).decode())
                print(f"   datasource.type = {d.get('type')}  artifactId = {d.get('artifactId')}")
            if p["path"].endswith("fewshots.json") and "/draft/" in p["path"]:
                d = json.loads(base64.b64decode(p["payload"]).decode())
                print(f"   fewShots count = {len(d.get('fewShots', []))}")
    else:
        print("   (no readback parts — confirm in portal)")
    print(f"\nOK. Data Agent '{AGENT_NAME}' deployed + published.")
    print("   Open it in the Fabric portal and test: 'If GATE-05 congests, which VIP sponsors are impacted?'")


if __name__ == "__main__":
    main()
