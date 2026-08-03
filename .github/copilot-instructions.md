# Copilot Instructions — Live Event Operations (LEO demo)

## Mandatory Testing Gate
Before running ANY `deploy_*.py`, generator, or artifact script:
```bash
python -m pytest tests/ -v --tb=short
```
If ANY test fails → **STOP. Fix the code first. Do not proceed.**

## Project Context
- Python 3.12, Windows. Fabric API deploy scripts in `src/` (idempotent via `state.json`).
- LEO demo: **Fabric Graph + Ontology + Operations Agent** over live event-operations data
  (large-scale conference scale). Real-time (Eventhouse/KQL). Foundry = phase 2.
- Workspace name + capacity_id + tenant_id are read from `src/config.yaml` (copy `src/config.example.yaml`).
- Design source of truth: `docs/ARCHITECTURE.md`.

## Data split
- **Topology → Lakehouse** (NonTimeSeries): Edition, Zone (BIM m²), Gate, Sensor, Session, Customer, Sponsorship, Observation.
- **Telemetry → Eventhouse/KQL** (TimeSeries): telemetry_kpi (zones), telemetry_queue (gates), alarms, event_logs.
- The **Ontology** binds both; the **Graph** enables multi-hop RCA + impact.

## Deploy order (strict)
workspace → lakehouse (topology) → setup notebook (CSV→Delta) → eventhouse + KQL tables →
preload telemetry → ontology (NonTimeSeries + TimeSeries bindings) → **graph (deploy_graph.py + RefreshGraph)** →
kql dashboard (4 persona pages) → data activator → operations agent → data agent.
One command: `python deploy_all.py` (idempotent, tenant-guarded, ends with a warm-up).

## The storyline (AMGFL26)
- Culprit = access gate **GATE-05** (serves **Salle Aspen**) → **congestion peak** (queue wait ≈ 25 min).
- Aspen saturates (occupancy > 90, density > 4, comfort collapses) during flagship sessions
  **AI for Good / Beauty & AI / Smart City 2030**.
- Impact: sessions → **3 VIP sponsors** (Northwind Tech, Lumiere Beauty, City of Aurora).
- Answers the two brief questions: *was the session full?* / *when & where was the wait time highest?*

## The 4 persona reports = KQL Dashboard pages
Management · Production · Chefs de projet · Client (RTI_Event_Dashboard, real-time 30s refresh).

## Known pitfalls (inherited)
- Deploying an ontology via REST does NOT populate its Graph Model — build + push the graph definition + `jobType=RefreshGraph`.
- Operations Agent INSTRUCTIONS must stay minimal (Operational + Semantic sections only). Persona/remediation live in GOALS. ONE identifier per KQL table (ignore the other id column).
- A fresh Eventhouse throws a transient Kusto 520 on first ingest → retry (preload_telemetry has it).
- Never use `az rest` from Python subprocess (hangs). Use `requests` + `az account get-access-token`.

## Power BI report pitfalls (`deploy_report.py` — legacy PBIX)
- **Persona banner**: a legacy `textbox` over a colored `basicShape` band renders an OPAQUE white background (white title becomes invisible + shows a scrollbar). Fix = `vcObjects.background show=false` (transparent) + textbox `z` above the band. Put title+subtitle in ONE textbox (2 paragraphs) with generous height (~58px) — two tight stacked textboxes each add a scrollbar.
- **KPI cards**: the new `visualType: "cardVisual"` IGNORES `categoryLabel show=false`, so the English measure label stays and gets truncated. Use the CLASSIC `visualType: "card"` + `categoryLabels` (plural) `show=false`; value styled via `labels`; projection role `Values` (not `Data`). Keep the FR label as the container `vcObjects.title`.
- **Table `CouldNotResolveSemanticQueryDefinition`** ("two expressions with identical native reference name 'name'"): two columns share a property name (dim_customers.name + dim_zones.name). Fix = UNIQUE `NativeReferenceName` per column (pass a caption e.g. Sponsor/Zone).
- **Deploy looks hung but isn't**: `poll_operation` is silent up to 120s → the terminal backgrounds before the `✅`. Redirect output to a file (`python -u src/deploy_report.py *> _deploy_out.txt`) and read it; `state.json` `report_id` is written only on success. Reopen the report fully (or private window) to bust Fabric render cache after a redeploy.
- **Terminal PATH breaks** after venv activation (`cd`/`Set-Location` "not recognized"): restore with `$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine')+';'+[Environment]::GetEnvironmentVariable('Path','User')`.
