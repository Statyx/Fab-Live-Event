#!/usr/bin/env python3
"""
Deploy the Event Knowledge Graph ontology (Fabric IQ) over the topology Lakehouse.

8 topology entity types + 9 relationships. NonTimeSeries (Lakehouse) bindings for topology
PLUS TimeSeries (Eventhouse/KQL) bindings on Zone (telemetry_kpi) and Gate (telemetry_queue),
so the ontology unifies batch topology + live telemetry in one semantic layer.

NOTE: deploying via REST does NOT populate the child Graph Model — run deploy_graph.py
afterwards (build + push the graph definition + RefreshGraph). See graph-agent.
"""
import sys, json, base64, hashlib, uuid
from platform_env import bootstrap
bootstrap()

import requests
from helpers import (get_fabric_token, fabric_headers, load_config, load_state,
                     save_state, poll_operation, find_item)

VT = {"string": "String", "int64": "BigInt", "double": "Double",
      "datetime": "DateTime", "bool": "Boolean"}

# (name, lakehouse_table, key_cols[], cols=[(col, tmsl_type)])
ENTITIES = [
    ("Edition", "dim_editions", ["edition_id"], [
        ("edition_id", "string"), ("edition_name", "string"), ("venue", "string"),
        ("city", "string"), ("edition_type", "string")]),
    ("Zone", "dim_zones", ["zone_id"], [
        ("zone_id", "string"), ("name", "string"), ("edition_id", "string"), ("served_by_gate", "string"),
        ("room_type", "string"), ("surface_m2", "int64"), ("capacity", "int64"),
        ("is_premium", "bool"), ("status", "string")]),
    ("Gate", "dim_gates", ["gate_id"], [
        ("gate_id", "string"), ("edition_id", "string"), ("gate_type", "string"),
        ("vendor", "string"), ("model", "string"), ("role", "string")]),
    ("Sensor", "dim_sensors", ["sensor_id"], [
        ("sensor_id", "string"), ("gate_id", "string"), ("name", "string"),
        ("sample_rate_s", "int64"), ("admin_status", "string")]),
    ("Session", "dim_sessions", ["session_id"], [
        ("session_id", "string"), ("zone_id", "string"), ("name", "string"),
        ("capacity", "int64"), ("track", "string"), ("sponsor_id", "string")]),
    ("Customer", "dim_customers", ["customer_id"], [
        ("customer_id", "string"), ("name", "string"), ("segment", "string"), ("vip_flag", "bool")]),
    ("Sponsorship", "dim_sponsorships", ["sponsorship_id"], [
        ("sponsorship_id", "string"), ("name", "string"), ("package_tier", "string"),
        ("customer_id", "string"), ("zone_id", "string")]),
    ("Observation", "fact_observations", ["observation_id"], [
        ("observation_id", "string"), ("zone_id", "string"), ("category", "string"),
        ("severity", "string"), ("status", "string"), ("opened_at", "string"), ("comment", "string")]),
]

# (name, source_entity, target_entity, fk_table, source_key_cols[], target_fk_cols[])
RELATIONSHIPS = [
    ("EditionHasZone",       "Edition",     "Zone",     "dim_zones",         ["edition_id"],     ["zone_id"]),
    ("ZoneServedByGate",     "Zone",        "Gate",     "dim_zones",         ["zone_id"],        ["served_by_gate"]),
    ("GateAtEdition",        "Gate",        "Edition",  "dim_gates",         ["gate_id"],        ["edition_id"]),
    ("GateHasSensor",        "Gate",        "Sensor",   "dim_sensors",       ["gate_id"],        ["sensor_id"]),
    ("SessionInZone",        "Session",     "Zone",     "dim_sessions",      ["session_id"],     ["zone_id"]),
    ("SessionSponsoredBy",   "Session",     "Customer", "dim_sessions",      ["session_id"],     ["sponsor_id"]),
    ("SponsorshipForCustomer","Sponsorship","Customer", "dim_sponsorships",  ["sponsorship_id"], ["customer_id"]),
    ("SponsorshipInZone",    "Sponsorship", "Zone",     "dim_sponsorships",  ["sponsorship_id"], ["zone_id"]),
    ("ObservationInZone",    "Observation", "Zone",     "fact_observations", ["observation_id"], ["zone_id"]),
]

# TimeSeries bindings: bind live telemetry onto topology entities so the ontology unifies
# NonTimeSeries (topology) + TimeSeries (telemetry) in one semantic layer.
# Source = the Lakehouse shortcut tables (telemetry_kpi / telemetry_queue), which OneLake-mirror
# the Eventhouse KQL via the mirroring policy (deploy_kql_shortcuts.py). Lakehouse-backed
# TimeSeries resolves reliably through the graph (Fabric IQ) — a live KustoTable source did not.
# name -> (lakehouse_table, timestamp_col, entity_key_col, [(metric_col, valueType), ...])
TIMESERIES = {
    "Zone": ("telemetry_kpi",   "timestamp", "zone_id",
             [("kpi_name", "String"), ("value", "Double")]),
    "Gate": ("telemetry_queue", "timestamp", "gate_id",
             [("wait_time_s", "Double"), ("in_count", "BigInt")]),
}


def det_guid(seed: str) -> str:
    return str(uuid.UUID(bytes=hashlib.md5(seed.encode("utf-8")).digest()))


def b64(obj) -> str:
    return base64.b64encode(json.dumps(obj).encode("utf-8")).decode("ascii")


def print_step(n, total, msg):
    print(f"\n[{n}/{total}] {msg}\n" + "-" * 60)


def build_parts(workspace_id, lakehouse_id, ontology_name, kql_db_id, cluster_uri, kql_db_name):
    et_id, prop_id, key_prop = {}, {}, {}
    for i, (name, table, keys, cols) in enumerate(ENTITIES):
        eid = str(1001 + i); et_id[name] = eid
        base = 10000 + i * 100
        for j, (col, _t) in enumerate(cols):
            prop_id[(name, col)] = str(base + 1 + j)
        key_prop[name] = [prop_id[(name, k)] for k in keys]

    parts = []
    platform = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "Ontology", "displayName": ontology_name,
                     "description": "Live-event knowledge graph (8 topology entities, 9 relationships)."},
        "config": {"version": "2.0", "logicalId": det_guid("ONT-LEO-logicalId")},
    }
    parts.append({"path": ".platform", "payload": b64(platform), "payloadType": "InlineBase64"})
    parts.append({"path": "definition.json", "payload": b64({}), "payloadType": "InlineBase64"})

    for name, table, keys, cols in ENTITIES:
        eid = et_id[name]
        i = int(eid) - 1001
        non_key_str = [c for c, t in cols if t == "string" and c not in keys]
        disp_col = non_key_str[0] if non_key_str else keys[0]
        properties = [{"id": prop_id[(name, c)], "name": c, "redefines": None,
                       "baseTypeNamespaceType": None, "valueType": VT[t]} for c, t in cols]
        ts_props, ts_binding_part = [], None
        if name in TIMESERIES:
            kql_table, ts_col, key_col, metrics = TIMESERIES[name]
            tsb = 40000 + i * 100
            ts_props = [{"id": str(tsb + 1), "name": ts_col, "redefines": None,
                         "baseTypeNamespaceType": None, "valueType": "DateTime"}]
            pbinds = [{"sourceColumnName": key_col, "targetPropertyId": prop_id[(name, key_col)]},
                      {"sourceColumnName": ts_col, "targetPropertyId": str(tsb + 1)}]
            for j, (mcol, vt) in enumerate(metrics):
                pid = str(tsb + 2 + j)
                ts_props.append({"id": pid, "name": mcol, "redefines": None,
                                 "baseTypeNamespaceType": None, "valueType": vt})
                pbinds.append({"sourceColumnName": mcol, "targetPropertyId": pid})
            ts_guid = det_guid(f"TimeSeries-{eid}")
            ts_binding = {"id": ts_guid, "dataBindingConfiguration": {
                "dataBindingType": "TimeSeries", "timestampColumnName": ts_col,
                "propertyBindings": pbinds,
                "sourceTableProperties": {"sourceType": "LakehouseTable", "workspaceId": workspace_id,
                                          "itemId": lakehouse_id, "sourceTableName": kql_table,
                                          "sourceSchema": "dbo"}}}
            ts_binding_part = {"path": f"EntityTypes/{eid}/DataBindings/{ts_guid}.json",
                               "payload": b64(ts_binding), "payloadType": "InlineBase64"}
        entity_def = {
            "id": eid, "namespace": "usertypes", "baseEntityTypeId": None, "name": name,
            "entityIdParts": key_prop[name], "displayNamePropertyId": prop_id[(name, disp_col)],
            "namespaceType": "Custom", "visibility": "Visible",
            "properties": properties, "timeseriesProperties": ts_props,
        }
        parts.append({"path": f"EntityTypes/{eid}/definition.json", "payload": b64(entity_def), "payloadType": "InlineBase64"})
        bind_guid = det_guid(f"NonTimeSeries-{eid}")
        binding = {"id": bind_guid, "dataBindingConfiguration": {
            "dataBindingType": "NonTimeSeries",
            "propertyBindings": [{"sourceColumnName": c, "targetPropertyId": prop_id[(name, c)]} for c, _t in cols],
            "sourceTableProperties": {"sourceType": "LakehouseTable", "workspaceId": workspace_id,
                                      "itemId": lakehouse_id, "sourceTableName": table, "sourceSchema": "dbo"}}}
        parts.append({"path": f"EntityTypes/{eid}/DataBindings/{bind_guid}.json", "payload": b64(binding), "payloadType": "InlineBase64"})
        if ts_binding_part:
            parts.append(ts_binding_part)

    for k, (rname, src, tgt, fk_table, src_keys, tgt_fks) in enumerate(RELATIONSHIPS):
        rid = str(3001 + k)
        rel_def = {"namespace": "usertypes", "id": rid, "name": rname, "namespaceType": "Custom",
                   "source": {"entityTypeId": et_id[src]}, "target": {"entityTypeId": et_id[tgt]}}
        parts.append({"path": f"RelationshipTypes/{rid}/definition.json", "payload": b64(rel_def), "payloadType": "InlineBase64"})
        ctx_guid = det_guid(f"Ctx-{rid}")
        src_refs = [{"sourceColumnName": col, "targetPropertyId": key_prop[src][i]} for i, col in enumerate(src_keys)]
        tgt_refs = [{"sourceColumnName": col, "targetPropertyId": key_prop[tgt][i]} for i, col in enumerate(tgt_fks)]
        ctx = {"id": ctx_guid,
               "dataBindingTable": {"workspaceId": workspace_id, "itemId": lakehouse_id,
                                    "sourceTableName": fk_table, "sourceSchema": "dbo", "sourceType": "LakehouseTable"},
               "sourceKeyRefBindings": src_refs, "targetKeyRefBindings": tgt_refs}
        parts.append({"path": f"RelationshipTypes/{rid}/Contextualizations/{ctx_guid}.json", "payload": b64(ctx), "payloadType": "InlineBase64"})

    return parts


def main():
    cfg = load_config(); state = load_state()
    api = cfg["fabric_api_base"]; ws = state["workspace_id"]; lh = state["lakehouse_id"]
    name = cfg["ontology_name"]
    kql_db_id = state["kql_database_id"]; cluster_uri = state["query_service_uri"]
    kql_db_name = cfg["eventhouse_name"]   # KQL database display name == eventhouse name
    token = get_fabric_token(); headers = fabric_headers(token)

    print(f"Deploying Ontology '{name}' — {len(ENTITIES)} entities, {len(RELATIONSHIPS)} relationships")

    print_step(1, 4, "Build definition parts")
    parts = build_parts(ws, lh, name, kql_db_id, cluster_uri, kql_db_name)
    print(f"   {len(parts)} parts")

    print_step(2, 4, "Create or find Ontology item")
    ont_id = state.get("ontology_id")
    if ont_id:
        try: find_item(token, api, ws, name, "Ontology")
        except RuntimeError: ont_id = None
    if not ont_id:
        try:
            ont_id = find_item(token, api, ws, name, "Ontology")["id"]
        except RuntimeError:
            r = requests.post(f"{api}/workspaces/{ws}/items", headers=headers,
                              json={"displayName": name, "type": "Ontology", "description": "Event knowledge graph (Fabric IQ)"})
            if r.status_code in (200, 201): ont_id = r.json()["id"]
            elif r.status_code == 202:
                op = r.headers.get("x-ms-operation-id")
                if op: poll_operation(token, api, op)
                ont_id = find_item(token, api, ws, name, "Ontology")["id"]
            else: raise RuntimeError(f"Create Ontology failed ({r.status_code}): {r.text[:400]}")
        print(f"   id: {ont_id}")
    else:
        print(f"   reusing: {ont_id}")

    print_step(3, 4, "Push full definition (updateDefinition)")
    resp = requests.post(f"{api}/workspaces/{ws}/items/{ont_id}/updateDefinition",
                         headers=headers, json={"definition": {"parts": parts}}, timeout=120)
    if resp.status_code in (200, 201):
        print("   accepted")
    elif resp.status_code == 202:
        op = resp.headers.get("x-ms-operation-id")
        if op: poll_operation(token, api, op)
        print("   accepted (async)")
    else:
        raise RuntimeError(f"updateDefinition failed ({resp.status_code}): {resp.text[:600]}")

    print_step(4, 4, "Persist state")
    state["ontology_id"] = ont_id; save_state(state)
    print(f"   ontology_id = {ont_id}")
    print("\nOK. Next: deploy_graph.py (build + push graph definition + RefreshGraph).")


if __name__ == "__main__":
    main()
