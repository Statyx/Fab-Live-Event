<div align="center">

# ⚡ Live Event Center — Publicis Live

### Real-time event operations on **Microsoft Fabric** — one ontology, autonomous + interactive agents, and a persona-driven portal.

![Microsoft Fabric](https://img.shields.io/badge/Microsoft-Fabric-0078D4?logo=microsoft&logoColor=white)
![Fabric IQ](https://img.shields.io/badge/Fabric_IQ-Ontology_+_Graph-6242C9)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Tests](https://img.shields.io/badge/tests-32_passing-2E9E44)
![Portal](https://img.shields.io/badge/Portal-FastAPI-009688?logo=fastapi&logoColor=white)
![Deploy](https://img.shields.io/badge/deploy-idempotent-896610)

*A data-first reference for **VivaTech-scale** live events — mirroring the Network Operations architecture, applied to the event domain.*

</div>

---

## ✨ What it is

A single **Fabric IQ ontology** unifies **static topology** (BIM zones, access gates, sessions, sponsors) with **live telemetry** (occupancy, crowd density, queue wait-time). It is consumed by three surfaces:

| Surface | Role |
|---|---|
| 🤖 **Operations Agent** | Autonomous, real-time detection over the Eventhouse — gate congestion, zone saturation, crowd density, comfort — with recommended remediation. |
| 💬 **Event Graph Data Agent** | Interactive natural-language Q&A over the ontology (root-cause + VIP-sponsor impact) via **GQL / KQL**. |
| 📊 **RTI Dashboard + Power BI report** | Real-time views: KQL dashboard (30 s refresh) + `RPT_Event_Ops` (4 pages). |

All of it is wrapped in a **web portal** (FastAPI) with **3 business views** — see [🖥️ The portal](#️-the-portal).

---

## 🎬 The storyline — pilot `AMGFL26`

> Access gate **GATE-05** (serving **Salle Aspen**) hits a **congestion peak** — security queue ≈ **25 min**.
> Aspen **saturates** during the flagship sessions *AI for Good / Beauty & AI / Smart City 2030* → **3 VIP sponsors at risk** (Microsoft, L'Oréal, Ville de Paris).

It answers the brief's two demo questions:

- 🟢 *Was the "AI for Good" session's room full?* → **yes**, occupancy saturated.
- 🟢 *When and where was the security wait-time highest?* → **GATE-05 at peak**.

---

## 🏗️ Architecture

```mermaid
flowchart LR
  subgraph Ingest
    CSV[BIM topology CSVs] --> LH[(Lakehouse<br/>NonTimeSeries)]
    TEL[Occupancy / queue telemetry] --> EH[(Eventhouse / KQL<br/>TimeSeries)]
  end
  LH --> ONT[Ontology + Graph<br/>Fabric IQ]
  EH --> ONT
  ONT --> OPS[🤖 Operations Agent]
  EH --> RX[Data Activator / Reflex]
  ONT --> DA[💬 Event Graph Data Agent]
  LH --> SM[Semantic Model<br/>Direct Lake]
  EH --> SM
  SM --> RPT[📊 Power BI RPT_Event_Ops]
  EH --> DASH[📈 RTI KQL Dashboard]
  RPT --> PORTAL[🖥️ Portal - 3 views]
  DA --> PORTAL
```

- **Topology → Lakehouse** (NonTimeSeries) · **Telemetry → Eventhouse/KQL** (TimeSeries).
- Both are bound into one **Ontology + Graph** (Fabric IQ) → multi-hop RCA + sponsor impact.
- Full design: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## 🚀 Quick start

```powershell
# 1. Config (capacity / tenant are pre-filled in this repo)
copy src\config.example.yaml src\config.yaml

# 2. ✅ Mandatory test gate — never deploy on red
python -m pytest tests/ -v --tb=short          # 32/32 offline

# 3. Deploy everything (idempotent — generates data, then ends with a warm-up)
python src\deploy_all.py

# 4. Launch the portal → http://localhost:8000
.\portal\start.ps1
```

Useful flags:

```powershell
python src\deploy_all.py --from ontology       # resume from a step
python src\deploy_all.py ontology graph         # run only these steps
python src\deploy_all.py --skip data_activator,kql_dashboard
python src\deploy_all.py --warmup               # warm-up only, no deploy (before a demo)
python src\deploy_all.py --no-warmup            # deploy without the trailing warm-up
python src\refresh_graph.py                     # re-ingest the graph after topology changes
```

---

## 🧱 Deploy pipeline (`deploy_all.py`, canonical order)

Each step is **idempotent** (state tracked in `src/state.json`):

| # | Step | Artifact |
|--:|---|---|
| 1 | `generate_data` | Synthetic `AMGFL26` topology + telemetry CSVs |
| 2 | `workspace` | Fabric workspace on capacity |
| 3 | `lakehouse` | Topology Delta tables (Edition, Zone, Gate, Sensor, Session, Customer, Sponsorship, Observation) |
| 4 | `setup_notebook` | CSV → Delta conversion |
| 5 | `eventhouse` | KQL tables (telemetry_kpi, telemetry_queue, alarms, event_logs) |
| 6 | `preload_telemetry` | Historical telemetry ingest (retries the transient Kusto 520) |
| 7 | `ontology` | NonTimeSeries + TimeSeries bindings |
| 8 | `graph` | Graph definition + `RefreshGraph` |
| 9 | `kql_dashboard` | RTI dashboard (4 persona pages) |
| 10 | `data_activator` | Reflex threshold alerting |
| 11 | `operations_agent` | Autonomous detection agent |
| 12 | `kql_shortcuts` | OneLake availability for KQL |
| 13 | `semantic_model` | Direct Lake model (topology + telemetry) |
| 14 | `data_agent` | Event Graph Data Agent (NL → GQL/KQL) |
| 15 | `report` | Power BI `RPT_Event_Ops` (4 pages) |

---

## 🖥️ The portal

`portal/` — a FastAPI app (`http://localhost:8000`) that embeds the report + a chat agent, organized in **3 business views** (decoupled from the report page / data-agent internals):

| View | Focus | Embedded pages | Agent greeting |
|---|---|---|---|
| 🛠️ **Admin Event** | Exploitation & terrain | Production + Chefs de Projet | *"assistant d'exploitation…"* |
| 🤝 **Client** | Espaces premium & sponsors | Client | *"Bienvenue ! Je suis l'assistant d'information…"* |
| 🎯 **Direction** | Pilotage global | Direction | *"assistant de pilotage…"* |

Views are **config-driven** in `portal/backend/main.py` (`AGENTS` registry) — the frontend auto-discovers them. Each view = report page(s) + accent + welcome message + suggested questions, all backed by the single Data Agent.

```powershell
.\portal\start.ps1          # http://localhost:8000  (API docs: /docs)
```

---

## 🎥 Demo (3 acts, real-time)

1. **Detection** — `python src\inject_event.py` fires a live congestion peak on GATE-05; the **Operations Agent** detects it autonomously and alerts with a recommended remediation.
2. **Root cause** — ask the Data Agent: *"Which gate serves zone ZONE-ASPEN?"* → **GATE-05**.
3. **Impact** — *"If GATE-05 congests, which VIP sponsors are impacted?"* → **3 VIP sponsors**.

Graph visual (Graph Model → Query → **Diagram view**):

```gql
MATCH p = (g:Gate {gate_id:'GATE-05'})<-[:ZoneServedByGate]-(z:Zone)
          <-[:SessionInZone]-(s:Session)-[:SessionSponsoredBy]->(cu:Customer)
WHERE cu.vip_flag = true
RETURN p
```

---

## 📁 Project layout

```
src/            deploy_*.py (idempotent via state.json) + generate_data / inject_event / refresh_graph
portal/         FastAPI portal (backend/main.py) + static/index.html  → 3 business views
tests/          offline smoke gate (pytest) — run before every deploy
docs/           ARCHITECTURE.md
taskflow/       Fabric Task Flow (import via portal)
presentation/   architecture-vision deck generator (pptxgenjs)
data/raw/       generated CSVs (gitignored)
```

---

## 🧭 Conventions & best practices

- ✅ **Test gate is mandatory** — `python -m pytest tests/ -v` before any `deploy_*.py`. On red: **stop, fix the code**.
- ♻️ **Idempotent deploys** — every step reads/writes `src/state.json`; re-running is safe.
- 🔐 **Secrets never committed** — `src/config.yaml`, `src/state.json`, `.vscode/mcp.json` are gitignored (use the `*.example` templates).
- ⚡ **F2+ capacity** — resume the capacity before a deploy/demo (Ontology / Graph / agents need it).
- 🧠 **Reports are Legacy PBIX** — see the report gotchas below.

---

## 🩹 Known pitfalls

<details>
<summary><b>Power BI report</b> (<code>deploy_report.py</code> — legacy PBIX)</summary>

- **Persona banner**: a legacy `textbox` over a colored band renders an **opaque white** background (white title invisible + scrollbar). Fix = transparent textbox background + z above the band; title+subtitle in **one** textbox (2 paragraphs, generous height).
- **KPI cards**: the new `cardVisual` **ignores** `categoryLabel show=false` → the English label stays and truncates. Use the **classic `card`** visual + `categoryLabels show=false`; value via `labels`; projection role `Values`.
- **Table `CouldNotResolveSemanticQueryDefinition`**: two columns share a native reference name → make `NativeReferenceName` **unique** per column.
- **Deploy looks hung but isn't**: the LRO poll is silent (≤120 s). Redirect output to a file and read it; `state.json` `report_id` is written only on success. Fully reopen the report to bust the render cache.
</details>

<details>
<summary><b>Deploy / infra</b></summary>

- Deploying an ontology via REST does **not** populate its Graph Model → build + push the graph definition + `jobType=RefreshGraph`.
- A fresh Eventhouse throws a transient Kusto **520** on first ingest → retry (`preload_telemetry` handles it).
- Never use `az rest` from a Python subprocess (hangs) → `requests` + `az account get-access-token`.
- Terminal PATH can break after venv activation → restore with `[Environment]::GetEnvironmentVariable('Path','Machine')+';'+[Environment]::GetEnvironmentVariable('Path','User')`.
</details>

---

## 📋 Requirements

- **Python 3.12**, **Azure CLI** logged in to the right tenant, a Fabric **F2+** capacity.
- `pip install -r requirements.txt` (root) and `pip install -r portal/backend/requirements.txt` (portal).
- **Fabric IQ** (Ontology + Graph) preview enabled on the tenant.

---

<div align="center">
<sub>Built for Publicis Live · Microsoft Fabric IQ demo · confidential — internal use.</sub>
</div>
