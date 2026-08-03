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
import sys, base64, json, uuid, time, argparse
# ── cross-platform PATH self-heal (venv activation can wipe it; az runs via subprocess) ──
from path_utils import restore_path, configure_stdout
restore_path()
configure_stdout()

import requests
from helpers import (load_config, load_state, save_state, get_fabric_token,
                     fabric_headers, poll_operation, b64encode_json, print_step)

AGENT_NAME = "Event_Graph_Agent"
AGENT_DESC = "Dual-source event ops agent: topology/RCA/impact via the ONT_Event_KnowledgeGraph ontology (GQL) + live telemetry numbers via the SM_Event_Analytics semantic model (DAX)."

AI_INSTRUCTIONS = """You are the Event Operations Agent for a Contoso Events control room.
You answer questions about a live event (zones, access gates, sessions, sponsors, observations and live
telemetry) by querying TWO data sources. ALWAYS answer by querying a source — NEVER from general
knowledge or assumptions. If a query returns nothing, say so explicitly rather than guessing.

## Two data sources — pick the right one for each question
1. ONT_Event_KnowledgeGraph (Ontology, GQL) — TOPOLOGY, RELATIONSHIPS, ROOT-CAUSE & IMPACT.
   Use it for: which gate serves a zone, which sessions/sponsors are impacted if a gate congests,
   which sponsors have a booth in a zone, sensors on a gate, VIP-sponsor impact, who sponsors what —
   anything about HOW entities connect (multi-hop traversals).
2. SM_Event_Analytics (Semantic Model, DAX) — LIVE TELEMETRY NUMBERS & AGGREGATES.
   Use it for: occupancy %, attendance / people count, crowd density, comfort index, m² utilization,
   saturated zones, gate wait time / queues, congestion counts, entries / exits / net flow, and any
   count / sum / avg / max of zones, gates, sessions, sponsors, sponsorships, capacities, observations.
   ALWAYS use the existing DAX measures (listed below) — never recompute with raw columns.

Routing rule: if the question asks for a NUMBER / metric / ranking (occupancy, wait, density, comfort,
counts, capacities), use the Semantic Model (DAX). If it asks HOW things connect or WHO is impacted,
use the Ontology (GQL). For "detect then impact" questions: get the number from the Semantic Model,
then traverse the graph from the offending gate/zone for the impact.

## Source 1 — Ontology (GQL): entities (node label : key properties)
- Edition (edition_id, edition_name, venue, city, edition_type) - the event instance.
- Zone (zone_id, edition_id, served_by_gate, room_type, surface_m2, capacity, is_premium, status) - a hall/room; surface_m2 & capacity come from BIM.
- Gate (gate_id, edition_id, gate_type, vendor, model, role) - an access gate/turnstile.
- Sensor (sensor_id, gate_id, name, sample_rate_s, admin_status) - a badge reader / CV camera on a gate.
- Session (session_id, zone_id, name, capacity, track, sponsor_id) - a conference in a zone.
- Customer (customer_id, name, segment, vip_flag) - a sponsor/exhibitor; vip_flag = true marks a VIP sponsor.
- Sponsorship (sponsorship_id, name, package_tier, customer_id, zone_id) - a sponsor's booth in a zone.
- Observation (observation_id, zone_id, category, severity, status, opened_at, comment) - a field/H&S observation.

### Relationships (edge label, direction matters)
- Edition -[EditionHasZone]-> Zone
- Zone -[ZoneServedByGate]-> Gate       (a zone is served by an access gate)
- Gate -[GateAtEdition]-> Edition
- Gate -[GateHasSensor]-> Sensor
- Session -[SessionInZone]-> Zone
- Session -[SessionSponsoredBy]-> Customer
- Sponsorship -[SponsorshipForCustomer]-> Customer
- Sponsorship -[SponsorshipInZone]-> Zone
- Observation -[ObservationInZone]-> Zone

### Key traversals
- Root cause (a zone is saturated -> which gate serves it -> which sensors):
  (z:Zone)-[:ZoneServedByGate]->(g:Gate)-[:GateHasSensor]->(se:Sensor)
- Impact (a gate congests -> who is affected) - traverse edges in REVERSE:
  (g:Gate)<-[:ZoneServedByGate]-(z:Zone)<-[:SessionInZone]-(s:Session)-[:SessionSponsoredBy]->(cu:Customer)
  Filter cu.vip_flag = true for VIP impact. Sponsor booths: (z)<-[:SponsorshipInZone]-(sp)-[:SponsorshipForCustomer]->(cu).
- In GQL, use the entity name as the node label and the relationship name as the edge label.

## Source 2 — Semantic Model (DAX): key measures (ALWAYS reuse, never recompute)
- Occupancy: [Avg Occupancy %], [Peak Occupancy %], [Avg m² Utilization %], [Saturated Zones (>90%)]
- Attendance: [Avg Attendees], [Peak Attendees]
- Density: [Avg Density Index], [Peak Density Index]
- Comfort: [Avg Comfort Index], [Min Comfort Index]
- Queue / gates: [Avg Wait (min)], [Peak Wait (min)], [Gates in Congestion (>10 min)]
- Flow: [Total Entries], [Total Exits], [Net Flow]
- Capacity / BIM & counts: [Total Zones], [Premium Zones], [Total Surface (m²)], [Total Capacity],
  [Total Gates], [Total Sessions], [Total Session Capacity], [Total Sponsors], [VIP Sponsors],
  [Total Sponsorships], [Total Observations], [High-Severity Observations], [Open Observations]
Group/filter with: dim_zones[name], dim_gates[gate_id], dim_sessions[name], dim_customers[name],
dim_sponsorships[package_tier], fact_observations[category], fact_observations[severity].
The telemetry measures already filter the right KPI (occupancy_pct, etc.) internally — do NOT filter
kpi_name yourself. Use EVALUATE with SUMMARIZECOLUMNS / ROW / TOPN. Filter one zone with
dim_zones[name] = "Salle Aspen" (or dim_zones[zone_id] = "ZONE-ASPEN").

## Domain notes
- Known incident: gate GATE-05 congests (queue wait ~25 min) and saturates the zone it serves, Salle Aspen
  (ZONE-ASPEN), during the flagship sessions "AI for Good", "Beauty & AI" and "Smart City 2030"
  (sponsored by VIP sponsors Northwind Tech, Lumiere Beauty and City of Aurora). RCA & impact -> ontology;
  the wait/occupancy figures -> semantic model.
- "VIP" sponsor = vip_flag = true (ontology) / measure [VIP Sponsors] (semantic model).
- Raw alarm rows / event logs live only in the telemetry KQL database (Operations Agent) - if asked for
  those specifically, note the source.

## Response format
- Lead with a direct one-line answer, figures as digits (e.g. "99.7 %", "25.9 min", "3 VIP sponsors").
- Then a short bullet list of the entities / values found.
- For impact questions, ALWAYS call out VIP sponsors (vip_flag = true) separately and first.
- For multi-hop answers, briefly state the path you traversed.
- Be concise and operational - your reader is an event operations lead / project manager."""

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
    ("Which sponsors have a booth in a premium zone?",
     "MATCH (sp:Sponsorship)-[:SponsorshipInZone]->(z:Zone) WHERE z.is_premium = true MATCH (sp)-[:SponsorshipForCustomer]->(cu:Customer) RETURN DISTINCT cu.name, z.name"),
    ("Which sessions are sponsored by a VIP sponsor?",
     "MATCH (s:Session)-[:SessionSponsoredBy]->(cu:Customer) WHERE cu.vip_flag = true RETURN s.name AS session, cu.name AS sponsor, s.track"),
]


# ── Semantic model source (SM_Event_Analytics) — live telemetry numbers via DAX ──

def build_sm_elements():
    """Selected tables / columns / measures exposed to the agent for DAX."""
    def _col(name, desc):
        return {"id": None, "display_name": name, "type": "semantic_model.column",
                "is_selected": True, "description": desc, "children": []}

    def _meas(name, desc):
        return {"id": None, "display_name": name, "type": "semantic_model.measure",
                "is_selected": True, "description": desc, "children": []}

    def _table(name, desc, children):
        return {"id": None, "display_name": name, "type": "semantic_model.table",
                "is_selected": True, "description": desc, "children": children}

    return [
        _table("dim_zones", "Venue zones/rooms (BIM: surface, capacity, premium)", [
            _col("zone_id", "Zone code"), _col("name", "Zone name"),
            _col("room_type", "Room type"), _col("is_premium", "Premium/VIP flag"),
            _meas("Total Zones", "Number of zones"),
            _meas("Premium Zones", "Number of premium/VIP zones"),
            _meas("Total Surface (m²)", "Total floor surface m²"),
            _meas("Total Capacity", "Total people capacity"),
        ]),
        _table("dim_gates", "Access gates with queue sensors", [
            _col("gate_id", "Gate code"), _col("role", "Gate role"),
            _meas("Total Gates", "Number of access gates"),
        ]),
        _table("dim_sessions", "Program sessions held in zones", [
            _col("session_id", "Session code"), _col("name", "Session name"), _col("track", "Program track"),
            _meas("Total Sessions", "Number of sessions"),
            _meas("Total Session Capacity", "Total seats across sessions"),
        ]),
        _table("dim_customers", "Sponsors/customers (VIP-flagged)", [
            _col("name", "Sponsor name"), _col("segment", "Segment"), _col("vip_flag", "VIP flag"),
            _meas("Total Sponsors", "Number of sponsors"),
            _meas("VIP Sponsors", "Number of VIP sponsors"),
        ]),
        _table("dim_sponsorships", "Sponsorship packages (customer x zone)", [
            _col("package_tier", "Package tier (Platinum/Gold/...)"),
            _meas("Total Sponsorships", "Number of sponsorship packages"),
        ]),
        _table("fact_observations", "Field observations by ops staff", [
            _col("category", "Category (Crowd, Safety, ...)"), _col("severity", "Severity (High/Medium/Low)"),
            _col("status", "Status (Open/Closed)"),
            _meas("Total Observations", "Number of observations"),
            _meas("High-Severity Observations", "High-severity observations"),
            _meas("Open Observations", "Open observations"),
        ]),
        _table("telemetry_kpi", "Zone KPI telemetry (occupancy, attendance, density, comfort, m² util)", [
            _meas("Avg Occupancy %", "Average zone occupancy %"),
            _meas("Peak Occupancy %", "Peak zone occupancy %"),
            _meas("Avg Attendees", "Average people count"),
            _meas("Peak Attendees", "Peak people count"),
            _meas("Avg Density Index", "Average crowd density (people/m²)"),
            _meas("Peak Density Index", "Peak crowd density"),
            _meas("Avg Comfort Index", "Average comfort index (0-100)"),
            _meas("Min Comfort Index", "Worst comfort index in context"),
            _meas("Avg m² Utilization %", "Average m² utilization %"),
            _meas("Saturated Zones (>90%)", "Zones peaking above 90% occupancy"),
        ]),
        _table("telemetry_queue", "Gate queue telemetry (wait time, entries, exits)", [
            _meas("Avg Wait (min)", "Average queue wait (minutes)"),
            _meas("Peak Wait (min)", "Peak queue wait (minutes)"),
            _meas("Total Entries", "Total people entering"),
            _meas("Total Exits", "Total people exiting"),
            _meas("Net Flow", "Net people flow (entries - exits)"),
            _meas("Gates in Congestion (>10 min)", "Gates peaking above 10 min wait"),
        ]),
    ]


SM_FEWSHOTS = [
    {"id": "sm-001", "question": "Quelle est l'occupation maximale et dans quelle zone ?",
     "query": 'EVALUATE TOPN(1, SUMMARIZECOLUMNS(dim_zones[name], "Peak Occ %", [Peak Occupancy %]), [Peak Occ %], DESC)'},
    {"id": "sm-002", "question": "Donne l'occupation maximale toutes zones confondues.",
     "query": 'EVALUATE ROW("Peak Occupancy %", [Peak Occupancy %])'},
    {"id": "sm-003", "question": "Quelle est l'occupation moyenne de la Salle Aspen ?",
     "query": 'EVALUATE CALCULATETABLE(ROW("Avg Occupancy %", [Avg Occupancy %], "Peak Occupancy %", [Peak Occupancy %]), dim_zones[name] = "Salle Aspen")'},
    {"id": "sm-004", "question": "Combien de zones sont saturées (au-dessus de 90 %) ?",
     "query": 'EVALUATE ROW("Saturated Zones", [Saturated Zones (>90%)])'},
    {"id": "sm-005", "question": "Occupation maximale par zone",
     "query": 'EVALUATE SUMMARIZECOLUMNS(dim_zones[name], "Peak Occ %", [Peak Occupancy %]) ORDER BY [Peak Occ %] DESC'},
    {"id": "sm-006", "question": "Quelle porte a le temps d'attente le plus élevé ?",
     "query": 'EVALUATE TOPN(1, SUMMARIZECOLUMNS(dim_gates[gate_id], "Peak Wait (min)", [Peak Wait (min)]), [Peak Wait (min)], DESC)'},
    {"id": "sm-007", "question": "Temps d'attente maximum par porte",
     "query": 'EVALUATE SUMMARIZECOLUMNS(dim_gates[gate_id], "Peak Wait (min)", [Peak Wait (min)]) ORDER BY [Peak Wait (min)] DESC'},
    {"id": "sm-008", "question": "Combien de portes sont en congestion (plus de 10 minutes) ?",
     "query": 'EVALUATE ROW("Gates in Congestion", [Gates in Congestion (>10 min)])'},
    {"id": "sm-009", "question": "Quelle est la fréquentation maximale de la journée ?",
     "query": 'EVALUATE ROW("Peak Attendees", [Peak Attendees])'},
    {"id": "sm-010", "question": "Fréquentation maximale par zone",
     "query": 'EVALUATE SUMMARIZECOLUMNS(dim_zones[name], "Peak Attendees", [Peak Attendees]) ORDER BY [Peak Attendees] DESC'},
    {"id": "sm-011", "question": "Quelles zones ont la plus forte densité de foule ?",
     "query": 'EVALUATE SUMMARIZECOLUMNS(dim_zones[name], "Peak Density", [Peak Density Index]) ORDER BY [Peak Density] DESC'},
    {"id": "sm-012", "question": "Confort moyen par zone (la plus basse en premier)",
     "query": 'EVALUATE SUMMARIZECOLUMNS(dim_zones[name], "Avg Comfort", [Avg Comfort Index]) ORDER BY [Avg Comfort] ASC'},
    {"id": "sm-013", "question": "Quel est le flux net d'entrées et de sorties ?",
     "query": 'EVALUATE ROW("Total Entries", [Total Entries], "Total Exits", [Total Exits], "Net Flow", [Net Flow])'},
    {"id": "sm-014", "question": "Nombre d'entrées par porte",
     "query": 'EVALUATE SUMMARIZECOLUMNS(dim_gates[gate_id], "Total Entries", [Total Entries]) ORDER BY [Total Entries] DESC'},
    {"id": "sm-015", "question": "Quelle est la capacité des sessions par zone ?",
     "query": 'EVALUATE SUMMARIZECOLUMNS(dim_zones[name], "Session Capacity", [Total Session Capacity]) ORDER BY [Session Capacity] DESC'},
    {"id": "sm-016", "question": "Répartis les observations par sévérité",
     "query": 'EVALUATE SUMMARIZECOLUMNS(fact_observations[severity], "Observations", [Total Observations])'},
    {"id": "sm-017", "question": "Répartis les observations par catégorie",
     "query": 'EVALUATE SUMMARIZECOLUMNS(fact_observations[category], "Observations", [Total Observations]) ORDER BY [Observations] DESC'},
    {"id": "sm-018", "question": "Combien de sponsors VIP et de zones premium ?",
     "query": 'EVALUATE ROW("VIP Sponsors", [VIP Sponsors], "Premium Zones", [Premium Zones], "Total Sponsorships", [Total Sponsorships])'},
    {"id": "sm-019", "question": "Partenariats par niveau de package",
     "query": 'EVALUATE SUMMARIZECOLUMNS(dim_sponsorships[package_tier], "Sponsorships", [Total Sponsorships]) ORDER BY [Sponsorships] DESC'},
    {"id": "sm-020", "question": "Donne-moi un résumé global de la journée",
     "query": 'EVALUATE ROW("Peak Occupancy %", [Peak Occupancy %], "Saturated Zones", [Saturated Zones (>90%)], "Peak Wait (min)", [Peak Wait (min)], "Congested Gates", [Gates in Congestion (>10 min)], "Total Entries", [Total Entries], "VIP Sponsors", [VIP Sponsors])'},
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


def build_parts(ws, ont_id, ont_name, sm_id, sm_name):
    ont_folder = f"ontology-{ont_name}"
    sm_folder = f"semantic-model-{sm_name}"
    SCH = "https://developer.microsoft.com/json-schemas/fabric/item/dataAgent/definition"
    data_agent = {"$schema": f"{SCH}/dataAgent/2.1.0/schema.json"}
    stage = {"$schema": f"{SCH}/stageConfiguration/1.0.0/schema.json", "aiInstructions": AI_INSTRUCTIONS}

    ont_ds = {
        "$schema": f"{SCH}/dataSource/1.0.0/schema.json",
        "artifactId": ont_id, "workspaceId": ws, "displayName": ont_name, "type": "ontology",
        "userDescription": "Live-event knowledge graph: 8 entities (Edition, Zone, Gate, Sensor, Session, Customer, Sponsorship, Observation) and 9 relationships for topology, root-cause and sponsor-impact analysis.",
        "dataSourceInstructions": "Use for TOPOLOGY, RELATIONSHIPS, ROOT-CAUSE and IMPACT (GQL). Node label = entity name, edge label = relationship name. For impact traverse Gate <- Zone <- Session -> Customer and surface VIP sponsors (vip_flag = true). Do NOT use this source for telemetry numbers (occupancy, wait, density, comfort, counts) — use the semantic model instead.",
    }
    ont_fs = {"$schema": f"{SCH}/fewShots/1.0.0/schema.json",
              "fewShots": [{"id": str(uuid.uuid4()), "question": q, "query": gql} for q, gql in FEWSHOTS]}

    sm_ds = {
        "$schema": f"{SCH}/dataSource/1.0.0/schema.json",
        "artifactId": sm_id, "workspaceId": ws, "displayName": sm_name, "type": "semantic_model",
        "dataSourceInstructions": "Use for ALL live telemetry numbers and aggregates: occupancy %, attendance, density, comfort, m² utilization, saturated zones, gate wait/queue, congestion, entries/exits/net flow, and any count/sum/avg/max of zones, gates, sessions, sponsors, sponsorships, capacities, observations. ALWAYS reuse the existing DAX measures; NEVER filter kpi_name (the measures already filter the right KPI). Group with dim_zones[name] / dim_gates[gate_id]; filter a zone with dim_zones[name] = \"Salle Aspen\".",
        "elements": build_sm_elements(),
    }
    sm_fs = {"$schema": f"{SCH}/fewShots/1.0.0/schema.json", "fewShots": SM_FEWSHOTS}

    s = b64(stage)
    ont_ds_b, ont_fs_b = b64(ont_ds), b64(ont_fs)
    sm_ds_b, sm_fs_b = b64(sm_ds), b64(sm_fs)
    pub = b64({"$schema": f"{SCH}/publishInfo/1.0.0/schema.json",
               "description": f"{AGENT_NAME} -- dual-source (ontology + semantic model) -- published {time.strftime('%Y-%m-%d')}"})

    def _p(path, payload):
        return {"path": path, "payload": payload, "payloadType": "InlineBase64"}

    parts = [
        _p("Files/Config/data_agent.json", b64(data_agent)),
        _p("Files/Config/draft/stage_config.json", s),
        _p(f"Files/Config/draft/{ont_folder}/datasource.json", ont_ds_b),
        _p(f"Files/Config/draft/{ont_folder}/fewshots.json", ont_fs_b),
        _p(f"Files/Config/draft/{sm_folder}/datasource.json", sm_ds_b),
        _p(f"Files/Config/draft/{sm_folder}/fewshots.json", sm_fs_b),
        _p("Files/Config/publish_info.json", pub),
        _p("Files/Config/published/stage_config.json", s),
        _p(f"Files/Config/published/{ont_folder}/datasource.json", ont_ds_b),
        _p(f"Files/Config/published/{ont_folder}/fewshots.json", ont_fs_b),
        _p(f"Files/Config/published/{sm_folder}/datasource.json", sm_ds_b),
        _p(f"Files/Config/published/{sm_folder}/fewshots.json", sm_fs_b),
    ]
    return parts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delete", action="store_true")
    args, _ = ap.parse_known_args()  # ignore args passed to deploy_all (e.g. --from, --no-warmup)

    cfg = load_config(); st = load_state()
    api = cfg["fabric_api_base"]; ws = st["workspace_id"]
    ont_id = st["ontology_id"]; ont_name = cfg["ontology_name"]
    sm_id = st["semantic_model_id"]; sm_name = cfg["semantic_model_name"]
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

    print_step(1, 3, f"Create/Update Data Agent '{AGENT_NAME}' (sources: ontology {ont_name} + semantic model {sm_name})")
    parts = build_parts(ws, ont_id, ont_name, sm_id, sm_name)
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
