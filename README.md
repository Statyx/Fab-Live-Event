# Publicis Live — Live Event Center (LEC) on Microsoft Fabric

A **data-first live-event operations** reference built on Microsoft Fabric for **Publicis Live**
(VivaTech-scale events), mirroring the Network Operations architecture but for the **event domain**.

A single **Fabric IQ ontology** unifies static topology (BIM zones, access gates, sessions,
sponsors) with **live telemetry** (occupancy, crowd density, queue wait-time). It is consumed by:

- **Operations Agent** — autonomous, real-time detection over the Eventhouse (gate congestion,
  zone saturation, crowd density, comfort) with recommended remediation.
- **Data Agent** — interactive natural-language Q&A over the ontology (root-cause + VIP sponsor
  impact) via GQL.
- **RTI Dashboard** — real-time, **4 persona views** (Management, Production, Chefs de projet, Client).

## The storyline (pilot AMGFL26)
Access gate **GATE-05** (serving **Salle Aspen**) hits a **congestion peak** — security queue
≈ 25 min. Aspen **saturates** during the flagship sessions **AI for Good / Beauty & AI /
Smart City 2030** → **3 VIP sponsors** at risk (Microsoft, L'Oréal, Ville de Paris).
This answers the brief's two demo questions:
- *Was the "AI for Good" session's room full?* → yes, occupancy saturated.
- *When and where was the security wait-time highest?* → GATE-05 at peak.

## Architecture
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Topology → Lakehouse (NonTimeSeries);
telemetry → Eventhouse/KQL (TimeSeries); both bound into one **Ontology + Graph** (Fabric IQ).

## Quick start
```powershell
copy src\config.example.yaml src\config.yaml   # then fill capacity/tenant (pre-filled here)
python -m pytest tests/ -v --tb=short          # 28/28 offline gate
python src\generate_data.py                    # synthetic AMGFL26 data
python src\deploy_all.py                        # deploy everything (idempotent, warm-up)
```

Useful flags:
```powershell
python src\deploy_all.py --from ontology   # resume from a step
python src\deploy_all.py --warmup          # warm capacity before a demo
python src\refresh_graph.py                # re-ingest the graph after topology changes
```

## Demo (3 acts, real-time)
1. **Detection** — `python src\inject_event.py` (live congestion peak on GATE-05); the Operations
   Agent detects it autonomously and alerts with a recommended remediation.
2. **Root cause** — ask the Data Agent: *"Which gate serves zone ZONE-ASPEN?"* → GATE-05.
3. **Impact** — *"If GATE-05 congests, which VIP sponsors are impacted?"* → 3 VIP sponsors.

Graph visual (Graph Model → Query, toggle **Diagram view** or **Path query**):
```gql
MATCH p = (g:Gate {gate_id:'GATE-05'})<-[:ZoneServedByGate]-(z:Zone)
          <-[:SessionInZone]-(s:Session)-[:SessionSponsoredBy]->(cu:Customer)
WHERE cu.vip_flag = true
RETURN p
```

## The 4 persona reports
Delivered as **RTI_Event_Dashboard** pages (real-time, 30s refresh):
- **Management** — synthesis KPIs + decision points
- **Production** — gates, queues, density, alarms
- **Chefs de projet** — session/zone fill, comfort, observations
- **Client** — premium/VIP zones + sponsored-zone attendance

## Project layout
```
src/            deploy scripts (idempotent via state.json) + generate_data + inject_event
tests/          offline smoke gate (pytest) — run before every deploy
docs/           architecture
taskflow/       Fabric Task Flow (import via portal)
presentation/   architecture-vision deck generator (pptxgenjs)
data/raw/       generated CSVs (gitignored)
```

## Requirements
- Python 3.12, Azure CLI logged in to the right tenant, a Fabric F2+ capacity.
- `pip install -r requirements.txt`.
- Fabric IQ (Ontology + Graph) preview enabled on the tenant.
