#!/usr/bin/env python3
"""
Deploy Semantic Model SM_Event_Analytics — Direct Lake over LH_Event_Topology.

Star schema: topology dims (Delta) + telemetry facts (KQL shortcuts, see
deploy_kql_shortcuts.py). ~40 DAX measures for the 4 personas
(Management / Production / Chefs de projet / Client). Prep-for-AI annotations
(Copilot instructions, linguistic schema, verified answers) in FR.

Run deploy_kql_shortcuts.py FIRST and wait ~5 min for mirroring, so the
telemetry_kpi / telemetry_queue shortcut tables are populated before refresh.
"""
import sys
from platform_env import bootstrap
bootstrap()

import json, uuid
from pathlib import Path
import requests

sys.path.insert(0, str(Path(__file__).parent))
from helpers import (load_config, load_state, save_state,
                     get_fabric_token, fabric_headers,
                     b64encode_json, poll_operation, find_item, print_step)

API_BASE = None


def _tag():
    return str(uuid.uuid4())


def _col(name, data_type, desc="", fmt="", hidden=False, summarize_none=False):
    col = {"name": name, "dataType": data_type, "sourceColumn": name, "lineageTag": _tag()}
    if desc: col["description"] = desc
    if fmt: col["formatString"] = fmt
    if hidden: col["isHidden"] = True
    if summarize_none: col["summarizeBy"] = "none"
    return col


def _measure(name, expr, desc="", fmt="", folder=""):
    m = {"name": name, "expression": expr.split("\n"), "lineageTag": _tag()}
    if desc: m["description"] = desc
    if fmt: m["formatString"] = fmt
    if folder: m["displayFolder"] = folder
    return m


def _partition(table_name):
    return {"name": table_name, "mode": "directLake",
            "source": {"type": "entity", "entityName": table_name,
                       "expressionSource": "DatabaseQuery"}}


def build_model_bim(config, state):
    tables = []

    # ── dim_editions ─────────────────────────────────────────────
    tables.append({
        "name": "dim_editions", "lineageTag": _tag(),
        "description": "Event editions (the event instance / show)",
        "columns": [
            _col("edition_id", "string", "Edition code", summarize_none=True),
            _col("edition_name", "string", "Edition display name"),
            _col("venue", "string", "Venue"),
            _col("city", "string", "City"),
            _col("edition_type", "string", "Edition type (Flagship, ...)"),
        ],
        "measures": [
            _measure("Total Editions", "COUNTROWS(dim_editions)",
                     "Number of event editions", fmt="#,0", folder="Counts"),
        ],
        "partitions": [_partition("dim_editions")],
    })

    # ── dim_zones (BIM-backed) ───────────────────────────────────
    tables.append({
        "name": "dim_zones", "lineageTag": _tag(),
        "description": "Physical zones/rooms of the venue (BIM: surface, capacity, premium)",
        "columns": [
            _col("zone_id", "string", "Zone code", summarize_none=True),
            _col("name", "string", "Zone name"),
            _col("edition_id", "string", "Edition FK", hidden=True, summarize_none=True),
            _col("served_by_gate", "string", "Access gate serving this zone"),
            _col("room_type", "string", "Room type (Auditorium, Exhibition, ...)"),
            _col("surface_m2", "int64", "Floor surface in m²", fmt="#,0", summarize_none=True),
            _col("capacity", "int64", "Max capacity (people)", fmt="#,0", summarize_none=True),
            _col("is_premium", "boolean", "Premium / VIP zone flag"),
            _col("status", "string", "Zone status (open, ...)"),
        ],
        "measures": [
            _measure("Total Zones", "COUNTROWS(dim_zones)",
                     "Number of zones in scope", fmt="#,0", folder="Counts"),
            _measure("Premium Zones", "CALCULATE(COUNTROWS(dim_zones), dim_zones[is_premium] = TRUE())",
                     "Number of premium/VIP zones", fmt="#,0", folder="Counts"),
            _measure("Total Surface (m²)", "SUM(dim_zones[surface_m2])",
                     "Total floor surface across zones", fmt="#,0", folder="Capacity"),
            _measure("Total Capacity", "SUM(dim_zones[capacity])",
                     "Total people capacity across zones", fmt="#,0", folder="Capacity"),
        ],
        "partitions": [_partition("dim_zones")],
    })

    # ── dim_gates ────────────────────────────────────────────────
    tables.append({
        "name": "dim_gates", "lineageTag": _tag(),
        "description": "Access gates (entrances) with queue sensors",
        "columns": [
            _col("gate_id", "string", "Gate code", summarize_none=True),
            _col("edition_id", "string", "Edition FK", hidden=True, summarize_none=True),
            _col("gate_type", "string", "Gate type"),
            _col("vendor", "string", "Sensor vendor"),
            _col("model", "string", "Sensor model"),
            _col("role", "string", "Gate role (main, service, ...)"),
        ],
        "measures": [
            _measure("Total Gates", "COUNTROWS(dim_gates)",
                     "Number of access gates", fmt="#,0", folder="Counts"),
        ],
        "partitions": [_partition("dim_gates")],
    })

    # ── dim_sessions ─────────────────────────────────────────────
    tables.append({
        "name": "dim_sessions", "lineageTag": _tag(),
        "description": "Program sessions held in zones, optionally sponsored",
        "columns": [
            _col("session_id", "string", "Session code", summarize_none=True),
            _col("zone_id", "string", "Zone FK", hidden=True, summarize_none=True),
            _col("name", "string", "Session name"),
            _col("capacity", "int64", "Session seating capacity", fmt="#,0", summarize_none=True),
            _col("track", "string", "Program track"),
            _col("sponsor_id", "string", "Sponsoring customer FK", hidden=True, summarize_none=True),
        ],
        "measures": [
            _measure("Total Sessions", "COUNTROWS(dim_sessions)",
                     "Number of program sessions", fmt="#,0", folder="Counts"),
            _measure("Total Session Capacity", "SUM(dim_sessions[capacity])",
                     "Total seats across sessions", fmt="#,0", folder="Capacity"),
        ],
        "partitions": [_partition("dim_sessions")],
    })

    # ── dim_customers (sponsors) ─────────────────────────────────
    tables.append({
        "name": "dim_customers", "lineageTag": _tag(),
        "description": "Customers / sponsors, VIP-flagged",
        "columns": [
            _col("customer_id", "string", "Customer code", summarize_none=True),
            _col("name", "string", "Customer name"),
            _col("segment", "string", "Business segment"),
            _col("vip_flag", "boolean", "VIP sponsor flag"),
        ],
        "measures": [
            _measure("Total Sponsors", "COUNTROWS(dim_customers)",
                     "Number of sponsors/customers", fmt="#,0", folder="Counts"),
            _measure("VIP Sponsors", "CALCULATE(COUNTROWS(dim_customers), dim_customers[vip_flag] = TRUE())",
                     "Number of VIP sponsors", fmt="#,0", folder="Counts"),
        ],
        "partitions": [_partition("dim_customers")],
    })

    # ── dim_sponsorships ─────────────────────────────────────────
    tables.append({
        "name": "dim_sponsorships", "lineageTag": _tag(),
        "description": "Sponsorship packages linking a customer to a zone",
        "columns": [
            _col("sponsorship_id", "string", "Sponsorship code", summarize_none=True),
            _col("name", "string", "Sponsorship name"),
            _col("package_tier", "string", "Package tier (Platinum, Gold, ...)"),
            _col("customer_id", "string", "Customer FK", hidden=True, summarize_none=True),
            _col("zone_id", "string", "Zone FK", hidden=True, summarize_none=True),
        ],
        "measures": [
            _measure("Total Sponsorships", "COUNTROWS(dim_sponsorships)",
                     "Number of sponsorship packages", fmt="#,0", folder="Counts"),
        ],
        "partitions": [_partition("dim_sponsorships")],
    })

    # ── fact_observations ────────────────────────────────────────
    tables.append({
        "name": "fact_observations", "lineageTag": _tag(),
        "description": "Field observations logged by ops staff",
        "columns": [
            _col("observation_id", "string", "Observation code", summarize_none=True),
            _col("zone_id", "string", "Zone FK", hidden=True, summarize_none=True),
            _col("category", "string", "Observation category (Crowd, Safety, ...)"),
            _col("severity", "string", "Severity (High, Medium, Low)"),
            _col("status", "string", "Status (Open, Closed)"),
            _col("opened_at", "dateTime", "When the observation was opened", fmt="General Date"),
            _col("comment", "string", "Free-text comment"),
        ],
        "measures": [
            _measure("Total Observations", "COUNTROWS(fact_observations)",
                     "Number of field observations", fmt="#,0", folder="Observations"),
            _measure("High-Severity Observations",
                     'CALCULATE(COUNTROWS(fact_observations), fact_observations[severity] = "High")',
                     "Observations flagged High severity", fmt="#,0", folder="Observations"),
            _measure("Open Observations",
                     'CALCULATE(COUNTROWS(fact_observations), fact_observations[status] = "Open")',
                     "Observations still open", fmt="#,0", folder="Observations"),
        ],
        "partitions": [_partition("fact_observations")],
    })

    # ── telemetry_kpi (shortcut, long format) ────────────────────
    tables.append({
        "name": "telemetry_kpi", "lineageTag": _tag(),
        "description": "Zone KPI telemetry (long format: occupancy_pct, people_count, density_index, utilization_m2_pct, comfort_index). OneLake shortcut to the Eventhouse.",
        "columns": [
            _col("timestamp", "dateTime", "Sample time", fmt="General Date"),
            _col("zone_id", "string", "Zone FK", hidden=True, summarize_none=True),
            _col("gate_id", "string", "Gate FK", hidden=True, summarize_none=True),
            _col("kpi_name", "string", "KPI name"),
            _col("value", "double", "KPI value", fmt="#,0.0", summarize_none=True),
        ],
        "measures": [
            _measure("Avg Occupancy %", 'CALCULATE(AVERAGE(telemetry_kpi[value]), telemetry_kpi[kpi_name] = "occupancy_pct")',
                     "Average zone occupancy %", fmt="#,0.0", folder="Occupancy"),
            _measure("Peak Occupancy %", 'CALCULATE(MAX(telemetry_kpi[value]), telemetry_kpi[kpi_name] = "occupancy_pct")',
                     "Peak zone occupancy %", fmt="#,0.0", folder="Occupancy"),
            _measure("Avg Attendees", 'CALCULATE(AVERAGE(telemetry_kpi[value]), telemetry_kpi[kpi_name] = "people_count")',
                     "Average people count", fmt="#,0", folder="Attendance"),
            _measure("Peak Attendees", 'CALCULATE(MAX(telemetry_kpi[value]), telemetry_kpi[kpi_name] = "people_count")',
                     "Peak people count", fmt="#,0", folder="Attendance"),
            _measure("Avg Density Index", 'CALCULATE(AVERAGE(telemetry_kpi[value]), telemetry_kpi[kpi_name] = "density_index")',
                     "Average crowd density index (people/m²)", fmt="#,0.00", folder="Density"),
            _measure("Peak Density Index", 'CALCULATE(MAX(telemetry_kpi[value]), telemetry_kpi[kpi_name] = "density_index")',
                     "Peak crowd density index", fmt="#,0.00", folder="Density"),
            _measure("Avg Comfort Index", 'CALCULATE(AVERAGE(telemetry_kpi[value]), telemetry_kpi[kpi_name] = "comfort_index")',
                     "Average comfort index (0-100)", fmt="#,0.0", folder="Comfort"),
            _measure("Min Comfort Index", 'CALCULATE(MIN(telemetry_kpi[value]), telemetry_kpi[kpi_name] = "comfort_index")',
                     "Worst comfort index in context", fmt="#,0.0", folder="Comfort"),
            _measure("Avg m² Utilization %", 'CALCULATE(AVERAGE(telemetry_kpi[value]), telemetry_kpi[kpi_name] = "utilization_m2_pct")',
                     "Average m² utilization %", fmt="#,0.0", folder="Occupancy"),
            _measure("Saturated Zones (>90%)",
                     "COUNTROWS(FILTER(VALUES(dim_zones[zone_id]), [Peak Occupancy %] > 90))",
                     "Count of zones peaking above 90% occupancy", fmt="#,0", folder="Occupancy"),
        ],
        "partitions": [_partition("telemetry_kpi")],
    })

    # ── telemetry_queue (shortcut, wide) ─────────────────────────
    tables.append({
        "name": "telemetry_queue", "lineageTag": _tag(),
        "description": "Gate queue telemetry (wait_time_s, in_count, out_count). OneLake shortcut to the Eventhouse.",
        "columns": [
            _col("timestamp", "dateTime", "Sample time", fmt="General Date"),
            _col("gate_id", "string", "Gate FK", hidden=True, summarize_none=True),
            _col("zone_id", "string", "Zone FK", hidden=True, summarize_none=True),
            _col("wait_time_s", "double", "Queue wait time (seconds)", fmt="#,0.0", summarize_none=True),
            _col("in_count", "int64", "People entering in sample", fmt="#,0", summarize_none=True),
            _col("out_count", "int64", "People exiting in sample", fmt="#,0", summarize_none=True),
        ],
        "measures": [
            _measure("Avg Wait (min)", "DIVIDE(AVERAGE(telemetry_queue[wait_time_s]), 60)",
                     "Average queue wait in minutes", fmt="#,0.0", folder="Queue"),
            _measure("Peak Wait (min)", "DIVIDE(MAX(telemetry_queue[wait_time_s]), 60)",
                     "Peak queue wait in minutes", fmt="#,0.0", folder="Queue"),
            _measure("Total Entries", "SUM(telemetry_queue[in_count])",
                     "Total people entering", fmt="#,0", folder="Flow"),
            _measure("Total Exits", "SUM(telemetry_queue[out_count])",
                     "Total people exiting", fmt="#,0", folder="Flow"),
            _measure("Net Flow", "[Total Entries] - [Total Exits]",
                     "Net people flow (entries - exits)", fmt="#,0", folder="Flow"),
            _measure("Gates in Congestion (>10 min)",
                     "COUNTROWS(FILTER(VALUES(dim_gates[gate_id]), [Peak Wait (min)] > 10))",
                     "Count of gates peaking above 10 min wait", fmt="#,0", folder="Queue"),
        ],
        "partitions": [_partition("telemetry_queue")],
    })

    # ── Relationships (many → one) ───────────────────────────────
    relationships = [
        {"name": "rel_zone_edition", "fromTable": "dim_zones", "fromColumn": "edition_id",
         "toTable": "dim_editions", "toColumn": "edition_id"},
        {"name": "rel_gate_edition", "fromTable": "dim_gates", "fromColumn": "edition_id",
         "toTable": "dim_editions", "toColumn": "edition_id"},
        {"name": "rel_session_zone", "fromTable": "dim_sessions", "fromColumn": "zone_id",
         "toTable": "dim_zones", "toColumn": "zone_id"},
        {"name": "rel_session_sponsor", "fromTable": "dim_sessions", "fromColumn": "sponsor_id",
         "toTable": "dim_customers", "toColumn": "customer_id"},
        {"name": "rel_sponsorship_customer", "fromTable": "dim_sponsorships", "fromColumn": "customer_id",
         "toTable": "dim_customers", "toColumn": "customer_id"},
        {"name": "rel_sponsorship_zone", "fromTable": "dim_sponsorships", "fromColumn": "zone_id",
         "toTable": "dim_zones", "toColumn": "zone_id"},
        {"name": "rel_obs_zone", "fromTable": "fact_observations", "fromColumn": "zone_id",
         "toTable": "dim_zones", "toColumn": "zone_id"},
        {"name": "rel_kpi_zone", "fromTable": "telemetry_kpi", "fromColumn": "zone_id",
         "toTable": "dim_zones", "toColumn": "zone_id"},
        {"name": "rel_queue_gate", "fromTable": "telemetry_queue", "fromColumn": "gate_id",
         "toTable": "dim_gates", "toColumn": "gate_id"},
    ]

    for t in tables:
        for c in t.get("columns", []):
            if "lineageTag" not in c:
                c["lineageTag"] = _tag()

    rels = [{"name": r["name"], "fromTable": r["fromTable"], "fromColumn": r["fromColumn"],
             "toTable": r["toTable"], "toColumn": r["toColumn"],
             "crossFilteringBehavior": "oneDirection"} for r in relationships]

    # SQL endpoint from Lakehouse properties
    lh_id = state.get("lakehouse_id", "")
    lh_name = config.get("lakehouse_name", "LH_Event_Topology")
    sql_endpoint = state.get("lakehouse_sql_endpoint", "")
    if lh_id and not sql_endpoint:
        h_tmp = fabric_headers(get_fabric_token())
        r_lh = requests.get(f"{API_BASE}/workspaces/{state['workspace_id']}/lakehouses/{lh_id}", headers=h_tmp)
        if r_lh.status_code == 200:
            sql_endpoint = r_lh.json().get("properties", {}).get("sqlEndpointProperties", {}).get("connectionString", "")

    expressions = [{
        "name": "DatabaseQuery", "kind": "m", "lineageTag": _tag(),
        "expression": ["let",
                       f'    database = Sql.Database("{sql_endpoint}", "{lh_name}")',
                       "in", "    database"],
    }]

    model_bim = {
        "compatibilityLevel": 1604,
        "model": {
            "defaultPowerBIDataSourceVersion": "PowerBI_V3",
            "defaultMode": "directLake",
            "discourageImplicitMeasures": True,
            "tables": tables,
            "relationships": rels,
            "expressions": expressions,
            "culture": "fr-FR",
            "annotations": [
                {"name": "__PBI_CopilotInstructions", "value": (
                    "Ce modèle analyse l'exploitation d'un événement (salon/forum) en quasi-temps réel : occupation des zones, "
                    "files d'attente aux portes d'accès, sessions, sponsors et observations terrain. "
                    "Toujours utiliser les mesures existantes plutôt que des agrégations manuelles. "
                    "Occupation : [Avg Occupancy %], [Peak Occupancy %], [Avg m² Utilization %], [Saturated Zones (>90%)]. "
                    "Fréquentation : [Avg Attendees], [Peak Attendees]. Densité : [Avg Density Index], [Peak Density Index]. "
                    "Confort : [Avg Comfort Index], [Min Comfort Index]. "
                    "Files d'attente : [Avg Wait (min)], [Peak Wait (min)], [Gates in Congestion (>10 min)]. "
                    "Flux : [Total Entries], [Total Exits], [Net Flow]. "
                    "Capacité/BIM : [Total Zones], [Premium Zones], [Total Surface (m²)], [Total Capacity]. "
                    "Programme : [Total Sessions], [Total Session Capacity]. Sponsors : [Total Sponsors], [VIP Sponsors], [Total Sponsorships]. "
                    "Terrain : [Total Observations], [High-Severity Observations], [Open Observations]. "
                    "La télémétrie KPI est en format long (dim kpi_name) : les mesures filtrent déjà par kpi_name, ne pas re-filtrer. "
                    "Pour les zones/portes, utiliser dim_zones[name] / dim_gates[gate_id]. Pour les classements, utiliser TOPN avec les mesures existantes."
                )},
                {"name": "__PBI_LinguisticSchema", "value": json.dumps({
                    "Version": "1.0.0", "Language": "fr-FR", "DynamicImprovement": "HighConfidence",
                    "Entities": {
                        "telemetry_kpi": {"Definition": {"Binding": {"ConceptualEntity": "telemetry_kpi"}},
                                          "State": "Generated", "Terms": [["occupation"], ["kpi"], ["télémétrie"], ["fréquentation"]]},
                        "telemetry_queue": {"Definition": {"Binding": {"ConceptualEntity": "telemetry_queue"}},
                                            "State": "Generated", "Terms": [["file"], ["attente"], ["queue"], ["porte"]]},
                        "dim_zones": {"Definition": {"Binding": {"ConceptualEntity": "dim_zones"}},
                                      "State": "Generated", "Terms": [["zone"], ["salle"], ["espace"]]},
                        "dim_gates": {"Definition": {"Binding": {"ConceptualEntity": "dim_gates"}},
                                      "State": "Generated", "Terms": [["porte"], ["entrée"], ["accès"]]},
                        "dim_sessions": {"Definition": {"Binding": {"ConceptualEntity": "dim_sessions"}},
                                         "State": "Generated", "Terms": [["session"], ["conférence"], ["programme"]]},
                        "dim_customers": {"Definition": {"Binding": {"ConceptualEntity": "dim_customers"}},
                                          "State": "Generated", "Terms": [["sponsor"], ["client"], ["partenaire"]]},
                        "dim_sponsorships": {"Definition": {"Binding": {"ConceptualEntity": "dim_sponsorships"}},
                                             "State": "Generated", "Terms": [["sponsoring"], ["partenariat"], ["package"]]},
                        "fact_observations": {"Definition": {"Binding": {"ConceptualEntity": "fact_observations"}},
                                              "State": "Generated", "Terms": [["observation"], ["incident terrain"], ["remontée"]]},
                    },
                })},
                {"name": "PBI_ProTooling", "value": json.dumps(
                    ["DirectLakeOnOneLakeInWeb", "WebModelingEdit", "DaxQueryView_Desktop", "CopilotTooling", "MCP-PBIModeling"])},
                {"name": "__PBI_TimeIntelligenceEnabled", "value": "1"},
                {"name": "PBI_QueryOrder", "value": json.dumps(
                    [f"DirectLake - {config.get('lakehouse_name', 'LH_Event_Topology')}"])},
                {"name": "__PBI_VerifiedAnswers", "value": json.dumps([
                    {"Question": "Quelle est l'occupation maximale ?",
                     "Answer": {"Query": 'EVALUATE ROW("Peak Occupancy", [Peak Occupancy %])',
                                "Description": "Occupation maximale (%) toutes zones"}},
                    {"Question": "Quel est le temps d'attente maximum aux portes ?",
                     "Answer": {"Query": 'EVALUATE ROW("Peak Wait", [Peak Wait (min)])',
                                "Description": "Temps d'attente maximum en minutes"}},
                    {"Question": "Combien de zones sont saturées ?",
                     "Answer": {"Query": 'EVALUATE ROW("Saturated", [Saturated Zones (>90%)])',
                                "Description": "Nombre de zones au-dessus de 90% d'occupation"}},
                    {"Question": "Combien de sponsors VIP ?",
                     "Answer": {"Query": 'EVALUATE ROW("VIP", [VIP Sponsors])',
                                "Description": "Nombre de sponsors VIP"}},
                    {"Question": "Quelle porte est la plus congestionnée ?",
                     "Answer": {"Query": 'EVALUATE TOPN(1, ADDCOLUMNS(VALUES(dim_gates[gate_id]), "Wait", [Peak Wait (min)]), [Wait], DESC)',
                                "Description": "Porte avec le temps d'attente maximum"}},
                    {"Question": "Quelle zone a la plus forte occupation ?",
                     "Answer": {"Query": 'EVALUATE TOPN(1, ADDCOLUMNS(VALUES(dim_zones[name]), "Occ", [Peak Occupancy %]), [Occ], DESC)',
                                "Description": "Zone avec l'occupation maximale"}},
                ])},
            ],
        },
    }
    return model_bim


def main():
    config = load_config(); state = load_state()
    global API_BASE
    API_BASE = config["fabric_api_base"]
    ws_id = state.get("workspace_id")
    if not ws_id:
        print("Workspace not created. Run deploy_workspace.py first."); sys.exit(1)

    token = get_fabric_token(); headers = fabric_headers(token)
    sm_name = config["semantic_model_name"]

    print_step(1, 1, f"Deploying Semantic Model: {sm_name}")
    model_bim = build_model_bim(config, state)
    tcount = len(model_bim["model"]["tables"])
    mcount = sum(len(t.get("measures", [])) for t in model_bim["model"]["tables"])
    rcount = len(model_bim["model"]["relationships"])
    print(f"   {tcount} tables, {mcount} measures, {rcount} relationships")

    definition = {"parts": [
        {"path": "definition.pbism", "payload": b64encode_json({"version": "1.0"}),
         "payloadType": "InlineBase64"},
        {"path": "model.bim", "payload": b64encode_json(model_bim), "payloadType": "InlineBase64"},
    ]}

    sm_id = state.get("semantic_model_id")
    if sm_id:
        print(f"   updating existing model {sm_id}")
        resp = requests.post(f"{API_BASE}/workspaces/{ws_id}/semanticModels/{sm_id}/updateDefinition",
                             headers=headers, json={"definition": definition})
    else:
        try:
            existing = find_item(token, API_BASE, ws_id, sm_name, "SemanticModel")
            sm_id = existing["id"]
            print(f"   updating found model {sm_id}")
            resp = requests.post(f"{API_BASE}/workspaces/{ws_id}/semanticModels/{sm_id}/updateDefinition",
                                 headers=headers, json={"definition": definition})
        except RuntimeError:
            print("   creating new model...")
            resp = requests.post(f"{API_BASE}/workspaces/{ws_id}/items", headers=headers,
                                 json={"displayName": sm_name, "type": "SemanticModel",
                                       "description": "Live Event Operations — real-time event operations analytics (Direct Lake)",
                                       "definition": definition})

    if resp.status_code in (200, 201):
        sm_id = resp.json().get("id", sm_id)
    elif resp.status_code == 202:
        op_id = resp.headers.get("x-ms-operation-id", "")
        if op_id:
            print(f"   polling operation {op_id}...")
            poll_operation(token, API_BASE, op_id)
        if not sm_id:
            sm_id = find_item(token, API_BASE, ws_id, sm_name, "SemanticModel")["id"]
    else:
        raise RuntimeError(f"Deploy failed ({resp.status_code}): {resp.text[:300]}")

    state["semantic_model_id"] = sm_id; save_state(state)
    print(f"\nOK. Semantic model deployed: {sm_id}")
    print("   Open it in the workspace → verify Direct Lake tables load (telemetry needs mirroring done).")


if __name__ == "__main__":
    main()
