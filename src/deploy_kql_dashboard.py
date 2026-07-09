#!/usr/bin/env python3
"""
Deploy RTI_Event_Dashboard — a real-time KQL Dashboard over the event telemetry Eventhouse.
Built from the canonical pattern in Fabric-Brain/agents/rti-kusto-agent/kql_dashboard.md
(RealTimeDashboard.json schema v20, 24-col grid, card/line/bar/table tiles, 30s auto-refresh).

FOUR persona pages (the 4 target audiences of the brief):
  Management        — synthesis KPIs + decision points
  Production        — gates, queues, density, alarms (operational)
  Chefs de projet   — session/zone fill, comfort, observations
  Client            — premium/VIP zones, sponsored-zone attendance
"""
import os, sys, winreg, uuid
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
                     fabric_headers, find_item, b64encode_json, poll_operation)

DASHBOARD_NAME = "RTI_Event_Dashboard"


def _id():
    return str(uuid.uuid4())


def _stat(title, query, x, y, w, h, page, ds):
    return {"id": _id(), "title": title, "query": query,
            "layout": {"x": x, "y": y, "width": w, "height": h},
            "pageId": page, "dataSourceId": ds, "visualType": "card",
            "visualOptions": {"yAxisRight": False, "multiStat__textSize": "auto",
                              "multiStat__valueColumn": {"type": "infer"}},
            "usedParamVariables": []}


def _viz(title, query, vtype, x, y, w, h, page, ds, series=False):
    vo = {"xColumn": {"type": "infer"}, "yColumns": {"type": "infer"}, "hideTileTitle": False}
    if vtype == "line":
        vo["yAxisMinimumValue"] = {"type": "infer"}
        vo["yAxisMaximumValue"] = {"type": "infer"}
        vo["multipleYAxes"] = {"base": {"id": "-1", "columns": [], "label": "",
                                         "yAxisMinimumValue": None, "yAxisMaximumValue": None,
                                         "yAxisScale": "linear", "horizontalLines": []}, "additional": []}
        vo["hideLegend"] = False
    if series:
        vo["seriesColumns"] = {"type": "infer"}
    return {"id": _id(), "title": title, "query": query,
            "layout": {"x": x, "y": y, "width": w, "height": h},
            "pageId": page, "dataSourceId": ds, "visualType": vtype,
            "visualOptions": vo, "usedParamVariables": []}


def build_dashboard_json(cfg, state):
    ds_id = _id()
    pM, pP, pC, pK = _id(), _id(), _id(), _id()
    cluster = state["query_service_uri"]; db = cfg["eventhouse_name"]
    data_source = {"id": ds_id, "name": db, "clusterUri": cluster, "database": db,
                   "kind": "manual-kusto", "scopeId": "KustoDatabaseResource"}
    tiles = []

    # ── Page 1: MANAGEMENT (synthesis + decision) ────────────────
    tiles += [
        _stat("Peak attendees", "telemetry_kpi\n| where kpi_name == 'people_count'\n| summarize Peak = round(max(value), 0)", 0, 0, 6, 5, pM, ds_id),
        _stat("Avg occupancy %", "telemetry_kpi\n| where kpi_name == 'occupancy_pct'\n| summarize Occ = round(avg(value), 1)", 6, 0, 6, 5, pM, ds_id),
        _stat("Avg m2 utilization %", "telemetry_kpi\n| where kpi_name == 'utilization_m2_pct'\n| summarize Util = round(avg(value), 1)", 12, 0, 6, 5, pM, ds_id),
        _stat("Critical alarms", "alarms\n| where severity == 'Critical' and state == 'raised'\n| count", 18, 0, 6, 5, pM, ds_id),
        _viz("Average occupancy over the day (%)",
             "telemetry_kpi\n| where kpi_name == 'occupancy_pct'\n| summarize AvgOcc = round(avg(value), 1) by bin(timestamp, 15m)\n| order by timestamp asc",
             "line", 0, 5, 24, 8, pM, ds_id),
        _viz("m2 utilization by zone",
             "telemetry_kpi\n| where kpi_name == 'utilization_m2_pct'\n| summarize AvgUtil = round(avg(value), 1) by zone_id\n| top 10 by AvgUtil desc",
             "bar", 0, 13, 12, 8, pM, ds_id),
        _viz("Alarms by type",
             "alarms\n| summarize Count = count() by alarm_type\n| order by Count desc",
             "bar", 12, 13, 12, 8, pM, ds_id),
    ]

    # ── Page 2: PRODUCTION (gates / queues / density / alarms) ───
    tiles += [
        _stat("Gates in congestion", "telemetry_queue\n| where wait_time_s > 600\n| summarize Gates = dcount(gate_id)", 0, 0, 6, 5, pP, ds_id),
        _stat("Max wait (min)", "telemetry_queue\n| summarize round(max(wait_time_s)/60.0, 1)", 6, 0, 6, 5, pP, ds_id),
        _stat("Peak crowd density", "telemetry_kpi\n| where kpi_name == 'density_index'\n| summarize round(max(value), 2)", 12, 0, 6, 5, pP, ds_id),
        _stat("Critical alarms", "alarms\n| where severity == 'Critical' and state == 'raised'\n| count", 18, 0, 6, 5, pP, ds_id),
        _viz("Gate wait time over the day (by gate)",
             "telemetry_queue\n| summarize MaxWait = round(max(wait_time_s), 0) by bin(timestamp, 15m), gate_id\n| order by timestamp asc",
             "line", 0, 5, 24, 8, pP, ds_id, series=True),
        _viz("Worst gates by wait time",
             "telemetry_queue\n| summarize AvgWait = round(avg(wait_time_s), 0) by gate_id\n| top 10 by AvgWait desc",
             "bar", 0, 13, 12, 8, pP, ds_id),
        _viz("Latest alarms",
             "alarms\n| project timestamp, gate_id, alarm_type, severity, state\n| order by timestamp desc\n| take 20",
             "table", 12, 13, 12, 8, pP, ds_id),
    ]

    # ── Page 3: CHEFS DE PROJET (session/zone fill + comfort) ────
    tiles += [
        _viz("Zone occupancy (session fill proxy)",
             "telemetry_kpi\n| where kpi_name == 'occupancy_pct'\n| summarize AvgOcc = round(avg(value), 1) by zone_id\n| top 12 by AvgOcc desc",
             "bar", 0, 0, 12, 8, pC, ds_id),
        _viz("Zones peaking above 90% occupancy",
             "telemetry_kpi\n| where kpi_name == 'occupancy_pct'\n| summarize PeakOcc = round(max(value), 1) by zone_id\n| where PeakOcc > 90\n| order by PeakOcc desc",
             "bar", 12, 0, 12, 8, pC, ds_id),
        _viz("Comfort index over the day",
             "telemetry_kpi\n| where kpi_name == 'comfort_index'\n| summarize AvgComfort = round(avg(value), 1) by bin(timestamp, 15m)\n| order by timestamp asc",
             "line", 0, 8, 24, 8, pC, ds_id),
        _stat("Avg comfort index", "telemetry_kpi\n| where kpi_name == 'comfort_index'\n| summarize round(avg(value), 1)", 0, 16, 8, 5, pC, ds_id),
        _stat("Avg crowd density", "telemetry_kpi\n| where kpi_name == 'density_index'\n| summarize round(avg(value), 2)", 8, 16, 8, 5, pC, ds_id),
        _stat("Zones over 90% (count)", "telemetry_kpi\n| where kpi_name == 'occupancy_pct'\n| summarize PeakOcc = max(value) by zone_id\n| where PeakOcc > 90\n| count", 16, 16, 8, 5, pC, ds_id),
    ]

    # ── Page 4: CLIENT (premium / sponsored-zone attendance) ─────
    tiles += [
        _stat("Salle Aspen peak occupancy %", "telemetry_kpi\n| where kpi_name == 'occupancy_pct' and zone_id == 'ZONE-ASPEN'\n| summarize round(max(value), 1)", 0, 0, 8, 5, pK, ds_id),
        _stat("Salle Aspen peak attendees", "telemetry_kpi\n| where kpi_name == 'people_count' and zone_id == 'ZONE-ASPEN'\n| summarize round(max(value), 0)", 8, 0, 8, 5, pK, ds_id),
        _stat("Salle Aspen avg comfort", "telemetry_kpi\n| where kpi_name == 'comfort_index' and zone_id == 'ZONE-ASPEN'\n| summarize round(avg(value), 1)", 16, 0, 8, 5, pK, ds_id),
        _viz("Salle Aspen occupancy over the day (%)",
             "telemetry_kpi\n| where kpi_name == 'occupancy_pct' and zone_id == 'ZONE-ASPEN'\n| summarize Occ = round(avg(value), 1) by bin(timestamp, 15m)\n| order by timestamp asc",
             "line", 0, 5, 24, 8, pK, ds_id),
        _viz("Attendance by zone (people)",
             "telemetry_kpi\n| where kpi_name == 'people_count'\n| summarize Peak = round(max(value), 0) by zone_id\n| top 10 by Peak desc",
             "bar", 0, 13, 24, 8, pK, ds_id),
    ]

    return {
        "$schema": "https://dataexplorer.azure.com/static/d/schema/20/dashboard.json",
        "schema_version": "20", "title": DASHBOARD_NAME,
        "autoRefresh": {"enabled": True, "defaultInterval": "30s", "minInterval": "30s"},
        "dataSources": [data_source],
        "pages": [{"id": pM, "name": "Management"}, {"id": pP, "name": "Production"},
                  {"id": pC, "name": "Chefs de projet"}, {"id": pK, "name": "Client"}],
        "tiles": tiles, "parameters": [],
    }


def main():
    cfg = load_config(); state = load_state()
    api = cfg["fabric_api_base"]; ws = state["workspace_id"]
    token = get_fabric_token(); h = fabric_headers(token)

    print("Building dashboard definition (4 persona pages)...")
    dash = build_dashboard_json(cfg, state)
    print(f"   {len(dash['pages'])} pages, {len(dash['tiles'])} tiles")

    dash_id = state.get("kql_dashboard_id")
    if not dash_id:
        try:
            dash_id = find_item(token, api, ws, DASHBOARD_NAME, "KQLDashboard")["id"]
        except RuntimeError:
            pass
    if not dash_id:
        r = requests.post(f"{api}/workspaces/{ws}/items", headers=h,
                          json={"displayName": DASHBOARD_NAME, "type": "KQLDashboard",
                                "description": "Live event real-time dashboard (4 persona views)"})
        if r.status_code in (200, 201):
            dash_id = r.json()["id"]
        elif r.status_code == 202:
            op = r.headers.get("x-ms-operation-id")
            if op: poll_operation(token, api, op)
            dash_id = find_item(token, api, ws, DASHBOARD_NAME, "KQLDashboard")["id"]
        else:
            raise RuntimeError(f"Create dashboard failed ({r.status_code}): {r.text[:300]}")
        print(f"   created: {dash_id}")
    else:
        print(f"   reusing: {dash_id}")

    print("Uploading RealTimeDashboard.json definition...")
    body = {"definition": {"parts": [{"path": "RealTimeDashboard.json",
                                      "payload": b64encode_json(dash), "payloadType": "InlineBase64"}]}}
    ok = False
    for ep in [f"{api}/workspaces/{ws}/kqlDashboards/{dash_id}/updateDefinition",
               f"{api}/workspaces/{ws}/items/{dash_id}/updateDefinition"]:
        r = requests.post(ep, headers=h, json=body)
        if r.status_code in (200, 202):
            if r.status_code == 202:
                op = r.headers.get("x-ms-operation-id")
                if op: poll_operation(token, api, op)
            print(f"   definition uploaded ({r.status_code})"); ok = True; break
    if not ok:
        raise RuntimeError(f"updateDefinition failed: {r.status_code} {r.text[:300]}")

    state["kql_dashboard_id"] = dash_id; save_state(state)
    print(f"\nOK. Dashboard '{DASHBOARD_NAME}' ({dash_id}) — 4 persona pages, auto-refresh 30s.")


if __name__ == "__main__":
    main()
