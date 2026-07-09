#!/usr/bin/env python3
"""
Deploy Power BI Report RPT_Event_Ops — 4-page persona report over
SM_Event_Analytics (Direct Lake). Legacy PBIX format (report.json with
sections[].visualContainers[]) — never PBIR (renders blank in Fabric).

Pages (personas), each with its own accent color + a mix of visual types
(KPI cards, multi-colored bars/columns, donuts, time-series lines, a table):
  1. Direction   — pilotage global
  2. Production   — exploitation temps réel
  3. Chefs de projet — sessions & confort
  4. Client       — sponsors & zones premium

Design notes (from report-builder-agent/visual_catalog.legacy.md):
  - Multi-color bars: put the SAME category column in both Category AND Series,
    then hide the legend. Without Series every bar is the same Fluent-2 blue.
  - dataPoint.colorByCategory does NOT work via the REST API — use the Series
    trick instead.
  - Rounded cards: vcObjects.border show=true + radius 8L.
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

import json
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from helpers import (load_config, load_state, save_state,
                     get_fabric_token, fabric_headers,
                     b64encode_json, poll_operation, find_item, print_step)


# ── shared style fragments ──────────────────────────────────────────────────

def _rounded_border(color="#E1DFDD"):
    return [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}},
                            "color": {"solid": {"color": {"expr": {"Literal": {"Value": f"'{color}'"}}}}},
                            "radius": {"expr": {"Literal": {"Value": "10L"}}}}}]


def _shadow():
    return [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}},
                            "color": {"solid": {"color": {"expr": {"Literal": {"Value": "'#cccccc'"}}}}},
                            "preset": {"expr": {"Literal": {"Value": "'Custom'"}}},
                            "shadowBlur": {"expr": {"Literal": {"Value": "6L"}}},
                            "shadowDistance": {"expr": {"Literal": {"Value": "3L"}}},
                            "transparency": {"expr": {"Literal": {"Value": "80L"}}}}}]


def _vc_title(title, color="#252423", size="12D"):
    return [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}},
                            "text": {"expr": {"Literal": {"Value": f"'{title}'"}}},
                            "fontSize": {"expr": {"Literal": {"Value": size}}},
                            "fontColor": {"solid": {"color": {"expr": {"Literal": {"Value": f"'{color}'"}}}}}}}]


# ── visual factory functions ────────────────────────────────────────────────

def _card(name, x, y, w, h, table, measure, accent, title, z=1):
    alias = name[:1]
    return {
        "x": x, "y": y, "z": z, "width": w, "height": h,
        "config": json.dumps({
            "name": name, "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": z, "width": w, "height": h}}],
            "singleVisual": {
                "visualType": "cardVisual",
                "projections": {"Data": [{"queryRef": f"{table}.{measure}"}]},
                "prototypeQuery": {
                    "Version": 2,
                    "From": [{"Name": alias, "Entity": table, "Type": 0}],
                    "Select": [{"Measure": {"Expression": {"SourceRef": {"Source": alias}}, "Property": measure},
                                "Name": f"{table}.{measure}", "NativeReferenceName": measure}],
                },
                "drillFilterOtherVisuals": True,
                "objects": {
                    "outline": [{"properties": {"show": {"expr": {"Literal": {"Value": "false"}}}}}],
                    "calloutValue": [{"properties": {
                        "fontSize": {"expr": {"Literal": {"Value": "30D"}}},
                        "bold": {"expr": {"Literal": {"Value": "true"}}},
                        "color": {"solid": {"color": {"expr": {"Literal": {"Value": f"'{accent}'"}}}}},
                    }}],
                    "categoryLabel": [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}},
                                                      "fontSize": {"expr": {"Literal": {"Value": "9D"}}},
                                                      "color": {"solid": {"color": {"expr": {"Literal": {"Value": "'#8A8886'"}}}}}}}],
                },
                "vcObjects": {
                    "title": _vc_title(title, color="#605E5C", size="11D"),
                    "visualHeader": [{"properties": {"show": {"expr": {"Literal": {"Value": "false"}}}}}],
                    "visualHeaderTooltip": [{"properties": {"show": {"expr": {"Literal": {"Value": "false"}}}}}],
                    "background": [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}}}}],
                    "border": _rounded_border(),
                    "dropShadow": _shadow(),
                },
            }, "howCreated": "Copilot",
        }), "filters": "[]",
    }


def _bar(name, x, y, w, h, dim_table, dim_col, fact_table, measure, title, labels=True, z=1):
    """Horizontal multi-colored bar (Category=Series=dim_col)."""
    d, f = "d", "f"
    return {
        "x": x, "y": y, "z": z, "width": w, "height": h,
        "config": json.dumps({
            "name": name, "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": z, "width": w, "height": h}}],
            "singleVisual": {
                "visualType": "clusteredBarChart",
                "projections": {"Category": [{"queryRef": f"{dim_table}.{dim_col}"}],
                                "Y": [{"queryRef": f"{fact_table}.{measure}"}],
                                "Series": [{"queryRef": f"{dim_table}.{dim_col}"}]},
                "prototypeQuery": {
                    "Version": 2,
                    "From": [{"Name": d, "Entity": dim_table, "Type": 0},
                             {"Name": f, "Entity": fact_table, "Type": 0}],
                    "Select": [
                        {"Column": {"Expression": {"SourceRef": {"Source": d}}, "Property": dim_col},
                         "Name": f"{dim_table}.{dim_col}", "NativeReferenceName": dim_col},
                        {"Measure": {"Expression": {"SourceRef": {"Source": f}}, "Property": measure},
                         "Name": f"{fact_table}.{measure}", "NativeReferenceName": measure},
                    ],
                    "OrderBy": [{"Direction": 2, "Expression": {"Measure": {"Expression": {"SourceRef": {"Source": f}}, "Property": measure}}}],
                },
                "drillFilterOtherVisuals": True,
                "objects": {
                    "categoryAxis": [{"properties": {"fontSize": {"expr": {"Literal": {"Value": "10D"}}}}}],
                    "valueAxis": [{"properties": {"show": {"expr": {"Literal": {"Value": "false"}}}}}],
                    "labels": [{"properties": {"show": {"expr": {"Literal": {"Value": "true" if labels else "false"}}},
                                               "fontSize": {"expr": {"Literal": {"Value": "9D"}}}}}],
                    "legend": [{"properties": {"show": {"expr": {"Literal": {"Value": "false"}}}}}],
                },
                "vcObjects": {
                    "title": _vc_title(title),
                    "background": [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}}}}],
                    "border": _rounded_border(),
                    "dropShadow": _shadow(),
                },
            }, "howCreated": "Copilot",
        }), "filters": "[]",
    }


def _bar_single(name, x, y, w, h, table, col, measure, title, labels=True, z=1):
    """Horizontal multi-colored bar where category + measure share one table."""
    a = "s"
    return {
        "x": x, "y": y, "z": z, "width": w, "height": h,
        "config": json.dumps({
            "name": name, "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": z, "width": w, "height": h}}],
            "singleVisual": {
                "visualType": "clusteredBarChart",
                "projections": {"Category": [{"queryRef": f"{table}.{col}"}],
                                "Y": [{"queryRef": f"{table}.{measure}"}],
                                "Series": [{"queryRef": f"{table}.{col}"}]},
                "prototypeQuery": {
                    "Version": 2,
                    "From": [{"Name": a, "Entity": table, "Type": 0}],
                    "Select": [
                        {"Column": {"Expression": {"SourceRef": {"Source": a}}, "Property": col},
                         "Name": f"{table}.{col}", "NativeReferenceName": col},
                        {"Measure": {"Expression": {"SourceRef": {"Source": a}}, "Property": measure},
                         "Name": f"{table}.{measure}", "NativeReferenceName": measure},
                    ],
                    "OrderBy": [{"Direction": 2, "Expression": {"Measure": {"Expression": {"SourceRef": {"Source": a}}, "Property": measure}}}],
                },
                "drillFilterOtherVisuals": True,
                "objects": {
                    "categoryAxis": [{"properties": {"fontSize": {"expr": {"Literal": {"Value": "10D"}}}}}],
                    "valueAxis": [{"properties": {"show": {"expr": {"Literal": {"Value": "false"}}}}}],
                    "labels": [{"properties": {"show": {"expr": {"Literal": {"Value": "true" if labels else "false"}}},
                                               "fontSize": {"expr": {"Literal": {"Value": "9D"}}}}}],
                    "legend": [{"properties": {"show": {"expr": {"Literal": {"Value": "false"}}}}}],
                },
                "vcObjects": {
                    "title": _vc_title(title),
                    "background": [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}}}}],
                    "border": _rounded_border(),
                    "dropShadow": _shadow(),
                },
            }, "howCreated": "Copilot",
        }), "filters": "[]",
    }


def _column(name, x, y, w, h, dim_table, dim_col, fact_table, measure, title, z=1):
    """Vertical multi-colored column (Category=Series=dim_col)."""
    d, f = "d", "f"
    return {
        "x": x, "y": y, "z": z, "width": w, "height": h,
        "config": json.dumps({
            "name": name, "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": z, "width": w, "height": h}}],
            "singleVisual": {
                "visualType": "clusteredColumnChart",
                "projections": {"Category": [{"queryRef": f"{dim_table}.{dim_col}"}],
                                "Y": [{"queryRef": f"{fact_table}.{measure}"}],
                                "Series": [{"queryRef": f"{dim_table}.{dim_col}"}]},
                "prototypeQuery": {
                    "Version": 2,
                    "From": [{"Name": d, "Entity": dim_table, "Type": 0},
                             {"Name": f, "Entity": fact_table, "Type": 0}],
                    "Select": [
                        {"Column": {"Expression": {"SourceRef": {"Source": d}}, "Property": dim_col},
                         "Name": f"{dim_table}.{dim_col}", "NativeReferenceName": dim_col},
                        {"Measure": {"Expression": {"SourceRef": {"Source": f}}, "Property": measure},
                         "Name": f"{fact_table}.{measure}", "NativeReferenceName": measure},
                    ],
                    "OrderBy": [{"Direction": 2, "Expression": {"Measure": {"Expression": {"SourceRef": {"Source": f}}, "Property": measure}}}],
                },
                "drillFilterOtherVisuals": True,
                "objects": {
                    "categoryAxis": [{"properties": {"fontSize": {"expr": {"Literal": {"Value": "10D"}}}}}],
                    "valueAxis": [{"properties": {"fontSize": {"expr": {"Literal": {"Value": "10D"}}}}}],
                    "labels": [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}},
                                               "fontSize": {"expr": {"Literal": {"Value": "9D"}}}}}],
                    "legend": [{"properties": {"show": {"expr": {"Literal": {"Value": "false"}}}}}],
                },
                "vcObjects": {
                    "title": _vc_title(title),
                    "background": [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}}}}],
                    "border": _rounded_border(),
                    "dropShadow": _shadow(),
                },
            }, "howCreated": "Copilot",
        }), "filters": "[]",
    }


def _donut(name, x, y, w, h, cat_table, cat_col, val_table, measure, title, z=1):
    """Donut chart. cat_table may equal val_table (single alias)."""
    same = cat_table == val_table
    ca = "c"; va = "c" if same else "v"
    froms = [{"Name": ca, "Entity": cat_table, "Type": 0}]
    if not same:
        froms.append({"Name": va, "Entity": val_table, "Type": 0})
    return {
        "x": x, "y": y, "z": z, "width": w, "height": h,
        "config": json.dumps({
            "name": name, "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": z, "width": w, "height": h}}],
            "singleVisual": {
                "visualType": "donutChart",
                "projections": {"Category": [{"queryRef": f"{cat_table}.{cat_col}"}],
                                "Y": [{"queryRef": f"{val_table}.{measure}"}]},
                "prototypeQuery": {
                    "Version": 2, "From": froms,
                    "Select": [
                        {"Column": {"Expression": {"SourceRef": {"Source": ca}}, "Property": cat_col},
                         "Name": f"{cat_table}.{cat_col}", "NativeReferenceName": cat_col},
                        {"Measure": {"Expression": {"SourceRef": {"Source": va}}, "Property": measure},
                         "Name": f"{val_table}.{measure}", "NativeReferenceName": measure},
                    ],
                },
                "drillFilterOtherVisuals": True,
                "objects": {
                    "legend": [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}},
                                               "position": {"expr": {"Literal": {"Value": "'Right'"}}},
                                               "fontSize": {"expr": {"Literal": {"Value": "9D"}}}}}],
                    "labels": [{"properties": {"labelStyle": {"expr": {"Literal": {"Value": "'Category, percent of total'"}}},
                                               "fontSize": {"expr": {"Literal": {"Value": "9D"}}}}}],
                },
                "vcObjects": {
                    "title": _vc_title(title),
                    "background": [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}}}}],
                    "border": _rounded_border(),
                    "dropShadow": _shadow(),
                },
            }, "howCreated": "Copilot",
        }), "filters": "[]",
    }


def _line(name, x, y, w, h, axis_table, axis_col, val_table, measure, title, color=None, z=1):
    """Time-series line. axis_table may equal val_table (single alias)."""
    same = axis_table == val_table
    aa = "a"; va = "a" if same else "v"
    froms = [{"Name": aa, "Entity": axis_table, "Type": 0}]
    if not same:
        froms.append({"Name": va, "Entity": val_table, "Type": 0})
    obj = {
        "categoryAxis": [{"properties": {"fontSize": {"expr": {"Literal": {"Value": "9D"}}},
                                          "concatenateLabels": {"expr": {"Literal": {"Value": "false"}}}}}],
        "valueAxis": [{"properties": {"fontSize": {"expr": {"Literal": {"Value": "9D"}}}}}],
        "legend": [{"properties": {"show": {"expr": {"Literal": {"Value": "false"}}}}}],
    }
    if color:
        obj["dataPoint"] = [{"properties": {"fill": {"solid": {"color": {"expr": {"Literal": {"Value": f"'{color}'"}}}}}}}]
    return {
        "x": x, "y": y, "z": z, "width": w, "height": h,
        "config": json.dumps({
            "name": name, "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": z, "width": w, "height": h}}],
            "singleVisual": {
                "visualType": "lineChart",
                "projections": {"Category": [{"queryRef": f"{axis_table}.{axis_col}"}],
                                "Y": [{"queryRef": f"{val_table}.{measure}"}]},
                "prototypeQuery": {
                    "Version": 2, "From": froms,
                    "Select": [
                        {"Column": {"Expression": {"SourceRef": {"Source": aa}}, "Property": axis_col},
                         "Name": f"{axis_table}.{axis_col}", "NativeReferenceName": axis_col},
                        {"Measure": {"Expression": {"SourceRef": {"Source": va}}, "Property": measure},
                         "Name": f"{val_table}.{measure}", "NativeReferenceName": measure},
                    ],
                    "OrderBy": [{"Direction": 1, "Expression": {"Column": {"Expression": {"SourceRef": {"Source": aa}}, "Property": axis_col}}}],
                },
                "drillFilterOtherVisuals": True,
                "objects": obj,
                "vcObjects": {
                    "title": _vc_title(title),
                    "background": [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}}}}],
                    "border": _rounded_border(),
                    "dropShadow": _shadow(),
                },
            }, "howCreated": "Copilot",
        }), "filters": "[]",
    }


def _textbox(name, x, y, w, h, text, font_size="16pt", color="#252423"):
    return {
        "x": x, "y": y, "z": 0, "width": w, "height": h,
        "config": json.dumps({
            "name": name, "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": 0, "width": w, "height": h}}],
            "singleVisual": {"visualType": "textbox", "objects": {"general": [{"properties": {
                "paragraphs": [{"textRuns": [{"value": text, "textStyle": {
                    "fontFamily": "Segoe UI Semibold", "fontWeight": "bold",
                    "fontSize": font_size, "color": color}}],
                    "horizontalTextAlignment": "left"}]}}]}},
        }), "filters": "[]",
    }


def _table(name, x, y, w, h, items, title, z=1):
    """Table visual. items = [(table, prop, 'Column'|'Measure'), ...]"""
    tables = list(dict.fromkeys(t for t, _, _ in items))
    aliases = {t: chr(ord('a') + i) for i, t in enumerate(tables)}
    froms = [{"Name": aliases[t], "Entity": t, "Type": 0} for t in tables]
    proj = {"Values": [{"queryRef": f"{t}.{p}"} for t, p, _ in items]}
    selects = []
    for t, p, tp in items:
        a = aliases[t]
        if tp == "Column":
            selects.append({"Column": {"Expression": {"SourceRef": {"Source": a}}, "Property": p},
                            "Name": f"{t}.{p}", "NativeReferenceName": p})
        else:
            selects.append({"Measure": {"Expression": {"SourceRef": {"Source": a}}, "Property": p},
                            "Name": f"{t}.{p}", "NativeReferenceName": p})
    return {
        "x": x, "y": y, "z": z, "width": w, "height": h,
        "config": json.dumps({
            "name": name, "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": z, "width": w, "height": h}}],
            "singleVisual": {
                "visualType": "tableEx",
                "projections": proj,
                "prototypeQuery": {"Version": 2, "From": froms, "Select": selects},
                "drillFilterOtherVisuals": True,
                "objects": {
                    "values": [{"properties": {"fontSize": {"expr": {"Literal": {"Value": "10D"}}}}}],
                    "columnHeaders": [{"properties": {
                        "fontSize": {"expr": {"Literal": {"Value": "10D"}}},
                        "bold": {"expr": {"Literal": {"Value": "true"}}},
                        "fontColor": {"solid": {"color": {"expr": {"Literal": {"Value": "'#FFFFFF'"}}}}},
                        "backColor": {"solid": {"color": {"expr": {"Literal": {"Value": "'#605E5C'"}}}}},
                    }}],
                    "grid": [{"properties": {"gridVertical": {"expr": {"Literal": {"Value": "false"}}},
                                             "rowPadding": {"expr": {"Literal": {"Value": "4D"}}}}}],
                    "total": [{"properties": {"show": {"expr": {"Literal": {"Value": "false"}}}}}],
                },
                "vcObjects": {
                    "title": _vc_title(title),
                    "background": [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}}}}],
                    "border": _rounded_border(),
                    "dropShadow": _shadow(),
                },
            }, "howCreated": "Copilot",
        }), "filters": "[]",
    }


def _band(name, x, y, w, h, color):
    """Solid colored header band (page identity strip)."""
    return {
        "x": x, "y": y, "z": 0, "width": w, "height": h,
        "config": json.dumps({
            "name": name, "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": 0, "width": w, "height": h}}],
            "singleVisual": {"visualType": "basicShape", "objects": {
                "line": [{"properties": {"show": {"expr": {"Literal": {"Value": "false"}}}}}],
                "fill": [{"properties": {
                    "fillColor": {"solid": {"color": {"expr": {"Literal": {"Value": f"'{color}'"}}}}},
                    "transparency": {"expr": {"Literal": {"Value": "0L"}}},
                }}],
            }},
        }), "filters": "[]",
    }


# ── Report definition ───────────────────────────────────────────────────────

def build_report(state, config):
    ws_name = config["workspace_name"]
    sm_name = config["semantic_model_name"]
    sm_id = state["semantic_model_id"]
    theme = "CY26SU02"

    VIOLET, BLUE, GREEN, GOLD = "#6B4FBB", "#0F6CBD", "#0E7A4B", "#C19A1E"

    def header(prefix, accent, title, subtitle):
        return [
            _band(f"{prefix}_band", 0, 0, 1280, 64, accent),
            _textbox(f"{prefix}_t", 28, 12, 900, 30, title, "17pt", "#FFFFFF"),
            _textbox(f"{prefix}_s", 28, 40, 900, 20, subtitle, "10pt", "#EDEBFF"),
        ]

    # Page 1 — Direction
    p1 = header("d", VIOLET, "Live Event Center — Pilotage Direction",
                "AMGFL26 · vue consolidée de la journée · occupation, fréquentation, saturation") + [
        _card("c1", 28, 78, 238, 112, "telemetry_kpi", "Peak Attendees", VIOLET, "Fréquentation Max"),
        _card("c2", 278, 78, 238, 112, "telemetry_kpi", "Avg Occupancy %", VIOLET, "Occupation Moyenne"),
        _card("c3", 528, 78, 238, 112, "telemetry_kpi", "Saturated Zones (>90%)", "#C0392B", "Zones Saturées"),
        _card("c4", 778, 78, 238, 112, "telemetry_queue", "Peak Wait (min)", "#C0392B", "Attente Max (min)"),
        _card("c5", 1028, 78, 224, 112, "dim_customers", "VIP Sponsors", GOLD, "Sponsors VIP"),
        _line("l1", 28, 202, 760, 248, "telemetry_kpi", "timestamp", "telemetry_kpi", "Peak Occupancy %",
              "Occupation Max dans le Temps (pic de saturation)", color=VIOLET),
        _donut("dn1", 800, 202, 452, 248, "dim_zones", "name", "telemetry_kpi", "Peak Attendees",
               "Répartition de la Fréquentation par Zone"),
        _bar("b1", 28, 462, 1224, 246, "dim_gates", "gate_id", "telemetry_queue", "Peak Wait (min)",
             "Temps d'Attente Max par Porte d'Accès (GATE-05 = goulot)"),
    ]

    # Page 2 — Production
    p2 = header("p", BLUE, "Exploitation — Production Temps Réel",
                "Files d'attente, densité de foule, flux d'entrées, alertes terrain") + [
        _card("c6", 28, 78, 238, 112, "telemetry_queue", "Peak Wait (min)", "#C0392B", "Attente Max (min)"),
        _card("c7", 278, 78, 238, 112, "telemetry_queue", "Gates in Congestion (>10 min)", "#C0392B", "Portes Congestionnées"),
        _card("c8", 528, 78, 238, 112, "telemetry_kpi", "Peak Density Index", BLUE, "Densité Max"),
        _card("c9", 778, 78, 238, 112, "telemetry_queue", "Net Flow", BLUE, "Flux Net"),
        _card("c10", 1028, 78, 224, 112, "fact_observations", "High-Severity Observations", "#C0392B", "Alertes Critiques"),
        _line("l2", 28, 202, 760, 248, "telemetry_queue", "timestamp", "telemetry_queue", "Avg Wait (min)",
              "Temps d'Attente Moyen dans le Temps (montée de la file)", color=BLUE),
        _bar("b2", 800, 202, 452, 248, "dim_gates", "gate_id", "telemetry_queue", "Peak Wait (min)",
             "File Max par Porte", labels=False),
        _column("col1", 28, 462, 1224, 246, "dim_zones", "name", "telemetry_kpi", "Peak Density Index",
                "Densité de Foule Max par Zone"),
    ]

    # Page 3 — Chefs de projet
    p3 = header("g", GREEN, "Sessions & Confort — Chefs de Projet",
                "Confort ressenti, utilisation des m², observations terrain par catégorie & sévérité") + [
        _card("c11", 28, 78, 238, 112, "telemetry_kpi", "Avg Comfort Index", GREEN, "Confort Moyen"),
        _card("c12", 278, 78, 238, 112, "telemetry_kpi", "Min Comfort Index", "#C0392B", "Confort Min"),
        _card("c13", 528, 78, 238, 112, "telemetry_kpi", "Avg m² Utilization %", GREEN, "Utilisation m²"),
        _card("c14", 778, 78, 238, 112, "dim_sessions", "Total Sessions", GREEN, "Sessions"),
        _card("c15", 1028, 78, 224, 112, "fact_observations", "Open Observations", GOLD, "Obs. Ouvertes"),
        _bar("b3", 28, 202, 760, 248, "dim_zones", "name", "telemetry_kpi", "Avg Comfort Index",
             "Confort Moyen par Zone (Salle Aspen la plus basse)"),
        _donut("dn2", 800, 202, 452, 248, "fact_observations", "severity", "fact_observations", "Total Observations",
               "Observations par Sévérité"),
        _bar("b4", 28, 462, 605, 246, "dim_zones", "name", "dim_sessions", "Total Session Capacity",
             "Capacité Sessions par Zone", labels=False),
        _bar_single("b5", 647, 462, 605, 246, "fact_observations", "category", "Total Observations",
                    "Observations par Catégorie"),
    ]

    # Page 4 — Client
    p4 = header("k", GOLD, "Sponsors & Zones Premium — Client",
                "Zones premium, partenariats, sponsors VIP et occupation des salles sponsorisées") + [
        _card("c16", 28, 78, 238, 112, "dim_zones", "Premium Zones", GOLD, "Zones Premium"),
        _card("c17", 278, 78, 238, 112, "dim_sponsorships", "Total Sponsorships", GOLD, "Partenariats"),
        _card("c18", 528, 78, 238, 112, "dim_customers", "VIP Sponsors", GOLD, "Sponsors VIP"),
        _card("c19", 778, 78, 238, 112, "telemetry_kpi", "Peak Occupancy %", "#C0392B", "Occupation Max"),
        _card("c20", 1028, 78, 224, 112, "telemetry_kpi", "Avg Comfort Index", GREEN, "Confort Moyen"),
        _bar("b6", 28, 202, 760, 248, "dim_zones", "name", "telemetry_kpi", "Peak Occupancy %",
             "Occupation Max par Zone (Salle Aspen en tête)"),
        _donut("dn3", 800, 202, 452, 248, "dim_sponsorships", "package_tier", "dim_sponsorships", "Total Sponsorships",
               "Partenariats par Niveau de Package"),
        _table("tbl1", 28, 462, 1224, 246, [
            ("dim_customers", "name", "Column"),
            ("dim_customers", "segment", "Column"),
            ("dim_sponsorships", "package_tier", "Column"),
            ("dim_zones", "name", "Column"),
        ], "Partenariats — Sponsor × Segment × Package × Zone"),
    ]

    report_config = {
        "version": "5.70",
        "themeCollection": {"baseTheme": {"name": theme, "version": {"visual": "2.6.0", "report": "3.1.0", "page": "2.3.0"}, "type": 2}},
        "activeSectionIndex": 0, "defaultDrillFilterOtherVisuals": True,
        "settings": {"useNewFilterPaneExperience": True, "allowChangeFilterTypes": True,
                     "useStylableVisualContainerHeader": True, "exportDataMode": 1},
    }

    report = {
        "config": json.dumps(report_config), "layoutOptimization": 0,
        "resourcePackages": [{"resourcePackage": {"name": "SharedResources", "type": 2,
                              "items": [{"type": 202, "path": f"BaseThemes/{theme}.json", "name": theme}], "disabled": False}}],
        "sections": [
            {"name": "Direction", "displayName": "Direction", "displayOption": 1, "width": 1280, "height": 720,
             "config": json.dumps({"name": "Direction"}), "filters": "[]", "visualContainers": p1},
            {"name": "Production", "displayName": "Production", "displayOption": 1, "width": 1280, "height": 720,
             "config": json.dumps({"name": "Production"}), "filters": "[]", "visualContainers": p2},
            {"name": "ChefsProjet", "displayName": "Chefs de Projet", "displayOption": 1, "width": 1280, "height": 720,
             "config": json.dumps({"name": "ChefsProjet"}), "filters": "[]", "visualContainers": p3},
            {"name": "Client", "displayName": "Client", "displayOption": 1, "width": 1280, "height": 720,
             "config": json.dumps({"name": "Client"}), "filters": "[]", "visualContainers": p4},
        ],
        "theme": theme,
    }

    conn_str = (f'Data Source="powerbi://api.powerbi.com/v1.0/myorg/{ws_name}";'
                f"initial catalog={sm_name};integrated security=ClaimsToken;semanticmodelid={sm_id}")
    pbir = {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
            "version": "4.0", "datasetReference": {"byConnection": {"connectionString": conn_str}}}
    # 8-color qualitative palette so each category slice/bar gets a distinct hue.
    base_theme = {"name": theme, "version": "5.70", "type": 2,
                  "dataColors": ["#6B4FBB", "#0F6CBD", "#0E7A4B", "#C19A1E", "#C0392B",
                                 "#E066A6", "#00A0B0", "#8764B8", "#D97706", "#4B6584"],
                  "background": "#FFFFFF", "foreground": "#252423", "tableAccent": "#6B4FBB",
                  "good": "#0E7A4B", "bad": "#C0392B", "neutral": "#C19A1E", "maximum": "#6B4FBB", "minimum": "#EFE6FB",
                  "textClasses": {
                      "callout": {"fontSize": 30, "fontFace": "Segoe UI Semibold", "color": "#252423"},
                      "title": {"fontSize": 12, "fontFace": "Segoe UI Semibold", "color": "#252423"},
                      "header": {"fontSize": 12, "fontFace": "Segoe UI Semibold", "color": "#252423"},
                      "label": {"fontSize": 10, "fontFace": "Segoe UI", "color": "#605E5C"},
                  }}
    return report, pbir, base_theme, theme


def main():
    config = load_config()
    state = load_state()
    api = config["fabric_api_base"]
    ws_id = state.get("workspace_id")
    sm_id = state.get("semantic_model_id")

    if not ws_id or not sm_id:
        print("❌ Prerequisites not met. Deploy workspace + semantic model first.")
        sys.exit(1)

    token = get_fabric_token()
    headers = fabric_headers(token)
    rpt_name = config["report_name"]

    print_step(1, 1, f"Deploying Report: {rpt_name}")
    report, pbir, base_theme, theme = build_report(state, config)
    pages = len(report["sections"])
    visuals = sum(len(s["visualContainers"]) for s in report["sections"])
    print(f"  📊 {pages} pages, {visuals} visuals")

    parts = [
        {"path": "report.json", "payload": b64encode_json(report), "payloadType": "InlineBase64"},
        {"path": "definition.pbir", "payload": b64encode_json(pbir), "payloadType": "InlineBase64"},
        {"path": f"StaticResources/SharedResources/BaseThemes/{theme}.json",
         "payload": b64encode_json(base_theme), "payloadType": "InlineBase64"},
    ]

    rpt_id = state.get("report_id")
    if not rpt_id:
        try:
            existing = find_item(token, api, ws_id, rpt_name, "Report")
            rpt_id = existing["id"]
        except RuntimeError:
            pass

    if rpt_id:
        resp = requests.post(f"{api}/workspaces/{ws_id}/reports/{rpt_id}/updateDefinition",
                             headers=headers, json={"definition": {"parts": parts}})
    else:
        resp = requests.post(f"{api}/workspaces/{ws_id}/items", headers=headers,
                             json={"displayName": rpt_name, "type": "Report",
                                   "description": "Live Event Center — rapport 4 personas",
                                   "definition": {"parts": parts}})

    if resp.status_code in (200, 201):
        rpt_id = resp.json().get("id", rpt_id)
    elif resp.status_code == 202:
        op_id = resp.headers.get("x-ms-operation-id", "")
        if op_id:
            poll_operation(token, api, op_id)
        if not rpt_id:
            rpt_id = find_item(token, api, ws_id, rpt_name, "Report")["id"]
    else:
        raise RuntimeError(f"Deploy failed ({resp.status_code}): {resp.text[:400]}")

    state["report_id"] = rpt_id
    save_state(state)
    print(f"\n✅ Report deployed: {rpt_id}")
    print(f"   Pages: {pages} | Visuals: {visuals}")


if __name__ == "__main__":
    main()
