"""
Financial Platform — FastAPI Backend (Multi-Agent Architecture)
Config-driven agent registry: each agent = a module with its own chat, report pages, and identity.
Uses OpenAI Assistants API format for Fabric Data Agents.
Uses DefaultAzureCredential (your az login) — no service principal needed.
"""

import os, asyncio, httpx, logging, json, base64, threading, time as _time, traceback
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

# ── Config ───────────────────────────────────────────────────
# Read live IDs from src/state.json (source of truth) so the portal never points
# at a stale/deleted report. Env vars override; hardcoded values are last-resort.
def _state() -> dict:
    try:
        sp = Path(__file__).resolve().parents[2] / "src" / "state.json"
        return json.loads(sp.read_text(encoding="utf-8"))
    except Exception:
        return {}

_ST = _state()
WORKSPACE_ID = os.getenv("WORKSPACE_ID") or _ST.get("workspace_id") or "535d5e13-ee94-480a-9bfb-58bb824b40e1"
REPORT_ID = os.getenv("REPORT_ID") or _ST.get("report_id") or "1c1b6655-1435-4fbb-af02-e672bda0172b"
DATASET_ID = os.getenv("DATASET_ID") or _ST.get("semantic_model_id") or "a4d0583c-9310-4e51-adac-dd59b75af6c1"
DATA_AGENT_ID = os.getenv("DATA_AGENT_ID") or _ST.get("data_agent_id") or "48d3a1ab-77c0-48bb-b5fa-f647af9c6aaf"
DASHBOARD_ID = os.getenv("DASHBOARD_ID") or _ST.get("kql_dashboard_id") or "f0400723-aa08-40a3-bc30-f8729059d851"
CLUSTER_URI = os.getenv("QUERY_SERVICE_URI") or _ST.get("query_service_uri") or ""


def _eventhouse_db() -> str:
    """KQL database name == eventhouse name (auto-created). Read from src/config.yaml
    with a tiny regex (no pyyaml dependency); env override; safe fallback."""
    env = os.getenv("EVENTHOUSE_DB")
    if env:
        return env
    try:
        import re as _re
        cp = Path(__file__).resolve().parents[2] / "src" / "config.yaml"
        m = _re.search(r'eventhouse_name:\s*"([^"]+)"', cp.read_text(encoding="utf-8"))
        if m:
            return m.group(1)
    except Exception:
        pass
    return "EH_Event_Telemetry"


EVENTHOUSE_DB = _eventhouse_db()
STAGE = os.getenv("AGENT_STAGE", "production")
API_VERSION = "2024-02-15-preview"
PBI_BASE = "https://api.powerbi.com/v1.0/myorg"
FABRIC_APP_BASE = "https://app.fabric.microsoft.com"
PBI_APP_BASE = "https://app.powerbi.com"

# ── Agent Registry ───────────────────────────────────────────
# 4 persona modules, all backed by the single Event_Graph_Agent Data Agent.
# Each persona = its own report page, accent, and suggested questions.
# To add a persona: add an entry here. The frontend auto-discovers them.
_DS = [{"id": DATASET_ID, "name": "SM_Event_Analytics",
        "scope": "Occupation, files d'attente, sessions, sponsors, observations"}]
_RP = [{"id": REPORT_ID, "name": "RPT_Event_Ops"}]

AGENTS: dict[str, dict] = {
    "admin": {
        "id": DATA_AGENT_ID,
        "name": "Admin Event",
        "description": "Exploitation & terrain : files d'attente, densité, sessions, confort, observations",
        "icon": "🛠️",
        "accent": "#027180",
        "datasets": _DS,
        "reports": _RP,
        "reportPages": ["Production", "Chefs de Projet"],
        "welcome": "Bonjour, je suis l'assistant d'exploitation de l'événement. Interrogez-moi sur les files d'attente, la densité de foule, les sessions, le confort et les alertes terrain.",
        "suggestions": [
            "Quelle porte est la plus congestionnée et de combien ?",
            "Quand le temps d'attente a-t-il été le plus élevé ?",
            "Quelles zones ont la plus forte densité de foule ?",
            "Quelle zone a le confort moyen le plus bas ?",
            "Combien d'observations critiques ont été remontées ?",
        ],
    },
    "client": {
        "id": DATA_AGENT_ID,
        "name": "Client",
        "description": "Espaces premium, sponsors VIP et affluence des salles",
        "icon": "🤝",
        "accent": "#863C41",
        "datasets": _DS,
        "reports": _RP,
        "reportPages": ["Client"],
        "welcome": "Bienvenue ! Je suis l'assistant d'information de l'événement. Posez-moi vos questions sur les espaces premium, les sponsors VIP et l'affluence des salles.",
        "suggestions": [
            "La Salle Aspen était-elle pleine, et quand ?",
            "Quelles zones premium ont eu la plus forte occupation ?",
            "Liste les partenariats par niveau de package",
            "Quels sponsors VIP sont associés à quelles zones ?",
            "Quelle est l'occupation des salles sponsorisées ?",
        ],
    },
    "direction": {
        "id": DATA_AGENT_ID,
        "name": "Direction",
        "description": "Pilotage global : occupation, fréquentation, saturation, VIP",
        "icon": "🎯",
        "accent": "#00008F",
        "datasets": _DS,
        "reports": _RP,
        "reportPages": ["Direction"],
        "welcome": "Bonjour, je suis l'assistant de pilotage de l'événement. Interrogez-moi sur l'occupation, la fréquentation, la saturation et l'impact sur les sponsors VIP.",
        "suggestions": [
            "Quelle est l'occupation maximale et dans quelle zone ?",
            "Combien de zones sont saturées (au-dessus de 90 %) ?",
            "Quelle est la fréquentation maximale de la journée ?",
            "Combien de sponsors VIP et sur quelles zones ?",
            "Quel est le temps d'attente maximum aux portes d'accès ?",
        ],
    },
}


def _agent_base(agent_id: str) -> str:
    return (
        f"https://api.fabric.microsoft.com/v1/workspaces/{WORKSPACE_ID}"
        f"/dataAgents/{agent_id}/aiassistant/openai"
    )


# ── Auth ─────────────────────────────────────────────────────
from azure.identity import AzureCliCredential
credential = AzureCliCredential(process_timeout=30)  # longer timeout than default 10s
log = logging.getLogger("portal")

# Token cache: avoid repeated az cli subprocess calls (known to hang/timeout)
_token_cache: dict[str, tuple[str, float]] = {}  # scope -> (token, expires_on)
_token_lock = threading.Lock()  # prevent concurrent refresh stampede


def _cached_token(scope: str, force: bool = False) -> str:
    cached = _token_cache.get(scope)
    if not force and cached and cached[1] > _time.time() + 300:  # 5 min buffer
        return cached[0]
    with _token_lock:
        # Re-check inside the lock (another thread may have refreshed)
        cached = _token_cache.get(scope)
        if not force and cached and cached[1] > _time.time() + 300:
            return cached[0]
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                log.warning(f"Acquiring token for {scope} (attempt {attempt + 1})...")
                result = credential.get_token(scope)
                _token_cache[scope] = (result.token, result.expires_on)
                log.warning(f"Token acquired for {scope} (expires_on={result.expires_on})")
                return result.token
            except Exception as e:
                last_err = e
                log.warning(f"Token attempt {attempt + 1} failed: {e}")
                _time.sleep(0.5 * (attempt + 1))
        # All retries failed: reuse not-yet-expired cached token if any
        if cached and cached[1] > _time.time():
            log.warning(f"Token refresh failed after retries, reusing cached token: {last_err}")
            return cached[0]
        raise last_err  # type: ignore[misc]


def fabric_token() -> str:
    return _cached_token("https://api.fabric.microsoft.com/.default")


def pbi_token() -> str:
    return _cached_token("https://analysis.windows.net/powerbi/api/.default")


def fabric_headers():
    return {"Authorization": f"Bearer {fabric_token()}", "Content-Type": "application/json"}


def pbi_headers():
    return {"Authorization": f"Bearer {pbi_token()}", "Content-Type": "application/json"}


def agent_params():
    return {"stage": STAGE, "api-version": API_VERSION}


# ── Kusto (Eventhouse) data-plane query ──────────────────────
def kusto_token() -> str:
    """Data-plane token for the Fabric Eventhouse (audience = the cluster URI)."""
    return _cached_token(f"{CLUSTER_URI}/.default")


async def kusto_query(csl: str) -> list[dict]:
    """Run a read-only KQL query against the Eventhouse; return rows as dicts."""
    if not CLUSTER_URI:
        raise HTTPException(503, "clusterUri not configured (query_service_uri missing in state.json)")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{CLUSTER_URI}/v1/rest/query",
            headers={"Authorization": f"Bearer {kusto_token()}",
                     "Content-Type": "application/json"},
            json={"db": EVENTHOUSE_DB, "csl": csl},
        )
        if r.status_code != 200:
            raise HTTPException(502, f"Kusto query failed: {r.status_code} {r.text[:200]}")
        tables = r.json().get("Tables", [])
        if not tables:
            return []
        primary = tables[0]  # first table = the query result
        cols = [c["ColumnName"] for c in primary.get("Columns", [])]
        return [dict(zip(cols, row)) for row in primary.get("Rows", [])]


# ── App ──────────────────────────────────────────────────────
app = FastAPI(title="Live Event Center API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_unhandled_errors(request: Request, call_next):
    """Catch any unhandled exception, log it with traceback, return JSON 502.
    Avoids opaque 502 with no clue in the terminal.
    """
    try:
        return await call_next(request)
    except HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        log.error(f"UNHANDLED {request.method} {request.url.path}: {e}\n{tb}")
        return JSONResponse(
            {"error": str(e), "path": request.url.path, "hint": "Try POST /api/admin/refresh-tokens"},
            status_code=502,
        )


@app.get("/api/health")
async def health():
    """Liveness + token freshness check. Hit this when you suspect a 502."""
    status: dict = {"ok": True, "tokens": {}}
    for label, scope in [
        ("fabric", "https://api.fabric.microsoft.com/.default"),
        ("powerbi", "https://analysis.windows.net/powerbi/api/.default"),
    ]:
        try:
            _cached_token(scope)
            cached = _token_cache.get(scope)
            expires_in = int(cached[1] - _time.time()) if cached else 0
            status["tokens"][label] = {"ok": True, "expires_in_s": expires_in}
        except Exception as e:
            status["ok"] = False
            status["tokens"][label] = {"ok": False, "error": str(e)}
    status["tenantId"] = _extract_tenant_id()
    return JSONResponse(status, status_code=200 if status["ok"] else 503)


@app.post("/api/admin/refresh-tokens")
async def refresh_tokens():
    """Force-refresh both tokens. Use this instead of restarting the server."""
    _token_cache.clear()
    out: dict = {}
    for label, scope in [
        ("fabric", "https://api.fabric.microsoft.com/.default"),
        ("powerbi", "https://analysis.windows.net/powerbi/api/.default"),
    ]:
        try:
            _cached_token(scope, force=True)
            out[label] = "refreshed"
        except Exception as e:
            out[label] = f"FAILED: {e}"
    return out


@app.on_event("startup")
async def _prewarm():
    """Pre-warm tokens at startup (avoids az cli timeout on first request)."""
    try:
        fabric_token()
        pbi_token()
        log.warning("Tokens pre-warmed OK")
    except Exception as e:
        log.warning(f"Token pre-warm failed (will retry on first request): {e}")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")


# ── Models ───────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str


class ToolTrace(BaseModel):
    tool: str
    arguments: str = ""
    output: str = ""

class ChatResponse(BaseModel):
    answer: str
    steps: list[str] = []
    queryTrace: list[ToolTrace] = []
    followUps: list[str] = []


# ── Agent Registry Endpoint ──────────────────────────────────
def _extract_tenant_id() -> str:
    """Decode the PBI token to extract the current tenant ID (no secrets)."""
    try:
        token = pbi_token()
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return claims.get("tid", "")
    except Exception:
        return ""


@app.get("/api/agents")
async def list_agents():
    """Return the agent registry (with public IDs only) for the frontend.

    Shape: { _meta: {...}, advisor: {...}, cashflow: {...}, ... }
    `_meta` carries cross-agent context (tenantId, workspaceId).
    """
    tenant_id = _extract_tenant_id()
    out: dict = {
        "_meta": {
            "tenantId": tenant_id,
            "workspaceId": WORKSPACE_ID,
            "dashboardId": DASHBOARD_ID,
            "clusterUri": CLUSTER_URI,
        }
    }
    for key, cfg in AGENTS.items():
        out[key] = {
            "name": cfg["name"],
            "description": cfg["description"],
            "icon": cfg["icon"],
            "accent": cfg["accent"],
            "agentId": cfg["id"],
            "datasets": cfg.get("datasets", []),
            "reports": cfg.get("reports", []),
            "reportPages": cfg["reportPages"],
            "suggestions": cfg["suggestions"],
            "welcome": cfg.get("welcome", ""),
        }
    return out


# ── Follow-up Suggestion Generator ──────────────────────────
import re

# Contextual follow-up templates per persona — keyed by topic keywords
_FOLLOWUP_TEMPLATES = {
    "direction": {
        "occupation|occup|saturation|satur": [
            "Quelle zone atteint le pic d'occupation et à quelle heure ?",
            "Combien de zones dépassent 90 % d'occupation ?",
            "Compare l'occupation entre la Salle Aspen et le Grand Auditorium",
        ],
        "fréquentation|frequentation|attend|visiteur": [
            "Quelle est la fréquentation par zone ?",
            "À quel moment la fréquentation est-elle maximale ?",
            "Quelle zone attire le plus de monde ?",
        ],
        "vip|sponsor": [
            "Quels sponsors VIP sont présents et sur quelles zones ?",
            "Combien de partenariats premium au total ?",
        ],
    },
    "admin": {
        "attente|file|queue|congestion|porte|gate": [
            "Quelle porte est la plus congestionnée ?",
            "Quand le temps d'attente a-t-il été le plus élevé ?",
            "Combien de portes dépassent 10 minutes d'attente ?",
        ],
        "densité|densite|foule": [
            "Quelles zones ont la densité de foule la plus forte ?",
            "La densité dépasse-t-elle le seuil de sécurité quelque part ?",
        ],
        "flux|entrée|entree|sortie": [
            "Quel est le flux net d'entrées sur la journée ?",
            "Quelle porte a le plus d'entrées ?",
        ],
        "alerte|alarme|incident|observation": [
            "Combien d'alertes critiques ont été remontées ?",
            "Quelles observations sont encore ouvertes ?",
        ],
        "confort|comfort": [
            "Quelle zone a le confort le plus bas ?",
            "Comment évolue le confort pendant les sessions phares ?",
        ],
        "session|programme|capacité|capacite": [
            "Quelle est la capacité des sessions par zone ?",
            "Quelles sessions se tiennent en Salle Aspen ?",
        ],
        "observation|catégorie|categorie|sévérité|severite": [
            "Répartis les observations par catégorie",
            "Combien d'observations de sévérité haute ?",
        ],
        "m²|m2|utilisation|surface": [
            "Quelle est l'utilisation moyenne des m² par zone ?",
            "Quelles zones sont sous-utilisées ?",
        ],
    },
    "client": {
        "aspen|salle|premium": [
            "La Salle Aspen était-elle pleine, et quand ?",
            "Quelles zones premium ont la plus forte occupation ?",
        ],
        "sponsor|partenariat|package|vip": [
            "Liste les partenariats par niveau de package",
            "Quels sponsors VIP sont associés à quelles zones ?",
        ],
        "occupation|fréquentation|frequentation": [
            "Quelle est l'occupation des salles sponsorisées ?",
            "Compare l'affluence des zones VIP et standard",
        ],
    },
}

# Universal follow-ups when no keyword matches
_UNIVERSAL_FOLLOWUPS = {
    "direction": [
        "Donne-moi une vue d'ensemble de la journée",
        "Quels sont les indicateurs clés à surveiller ?",
        "Où faut-il concentrer l'attention ?",
    ],
    "admin": [
        "Quel est l'état des files d'attente en ce moment ?",
        "Quelle porte pose le plus de problèmes ?",
        "Quel est le niveau de confort global ?",
    ],
    "client": [
        "La Salle Aspen était-elle pleine, et quand ?",
        "Quelles zones premium ont la plus forte occupation ?",
        "Liste les partenariats par niveau de package",
    ],
}


def _generate_followups(agent_key: str, question: str, answer: str) -> list[str]:
    """Generate 3 contextual follow-up suggestions based on the Q&A content."""
    templates = _FOLLOWUP_TEMPLATES.get(agent_key, {})
    combined = (question + " " + answer).lower()
    candidates = []

    for pattern, suggestions in templates.items():
        if re.search(pattern, combined):
            candidates.extend(suggestions)

    # Remove any that are too similar to the original question
    q_lower = question.lower()
    candidates = [c for c in candidates if c.lower() != q_lower]

    # Deduplicate preserving order
    seen = set()
    unique = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)

    if len(unique) >= 3:
        return unique[:3]

    # Pad with universal follow-ups
    for u in _UNIVERSAL_FOLLOWUPS.get(agent_key, []):
        if u not in seen and u.lower() != q_lower:
            unique.append(u)
            seen.add(u)
        if len(unique) >= 3:
            break

    return unique[:3]


# ── Data Agent Chat (OpenAI Assistants API) ──────────────────
@app.post("/api/agents/{agent_key}/chat", response_model=ChatResponse)
async def agent_chat(agent_key: str, req: ChatRequest):
    """Send a question to a specific Data Agent via OpenAI Assistants API."""
    if agent_key not in AGENTS:
        raise HTTPException(404, f"Unknown agent: {agent_key}")

    agent_cfg = AGENTS[agent_key]
    base = _agent_base(agent_cfg["id"])

    async with httpx.AsyncClient(timeout=120) as client:
        headers = fabric_headers()
        params = agent_params()

        # 1. Create assistant
        log.warning(f"[{agent_key}] Step 1: Create assistant")
        asst_resp = await client.post(
            f"{base}/assistants",
            headers=headers, params=params,
            json={"model": "irrelevant"},
        )
        if asst_resp.status_code not in (200, 201):
            raise HTTPException(502, f"Assistant creation failed: {asst_resp.status_code} {asst_resp.text}")
        assistant_id = asst_resp.json()["id"]

        # 2. Create fresh thread
        log.warning(f"[{agent_key}] Step 2: Create thread")
        thread_resp = await client.post(
            f"{base}/threads",
            headers=headers, params=params, json={},
        )
        if thread_resp.status_code not in (200, 201):
            raise HTTPException(502, f"Thread creation failed: {thread_resp.status_code} {thread_resp.text}")
        thread_id = thread_resp.json()["id"]

        try:
            # 3. Send user message
            log.warning(f"[{agent_key}] Step 3: Send message: {req.message[:80]}")
            msg_resp = await client.post(
                f"{base}/threads/{thread_id}/messages",
                headers=headers, params=params,
                json={"role": "user", "content": req.message},
            )
            if msg_resp.status_code not in (200, 201):
                log.error(f"[{agent_key}] Message send failed: {msg_resp.status_code} {msg_resp.text[:500]}")
                raise HTTPException(502, f"Message send failed: {msg_resp.status_code} - {msg_resp.text[:200]}")

            # 4. Create run
            log.warning(f"[{agent_key}] Step 4: Create run")
            run_resp = await client.post(
                f"{base}/threads/{thread_id}/runs",
                headers=headers, params=params,
                json={"assistant_id": assistant_id},
            )
            if run_resp.status_code not in (200, 201):
                raise HTTPException(502, f"Run creation failed: {run_resp.status_code}")
            run_id = run_resp.json()["id"]

            # 5. Poll run status
            log.warning(f"[{agent_key}] Step 5: Polling...")
            for _ in range(60):
                await asyncio.sleep(2)
                status_resp = await client.get(
                    f"{base}/threads/{thread_id}/runs/{run_id}",
                    headers=fabric_headers(), params=params,
                )
                if status_resp.status_code != 200:
                    continue
                status = status_resp.json().get("status")
                log.warning(f"[{agent_key}] Poll: {status}")
                if status in ("completed", "failed", "cancelled", "expired"):
                    break

            # 6. Get latest assistant message
            msgs_resp = await client.get(
                f"{base}/threads/{thread_id}/messages",
                headers=fabric_headers(), params=params,
            )
            answer = ""
            if msgs_resp.status_code == 200:
                for msg in msgs_resp.json().get("data", []):
                    if msg.get("role") == "assistant":
                        for content in msg.get("content", []):
                            if content.get("type") == "text":
                                answer += content["text"].get("value", "")
                        break  # newest assistant message only

            # 7. Get run steps
            steps = []
            query_trace = []
            steps_resp = await client.get(
                f"{base}/threads/{thread_id}/runs/{run_id}/steps",
                headers=fabric_headers(), params=params,
            )
            if steps_resp.status_code == 200:
                for step in steps_resp.json().get("data", []):
                    for tc in step.get("step_details", {}).get("tool_calls", []):
                        fn_obj = tc.get("function", {})
                        fn = fn_obj.get("name", "")
                        if fn:
                            steps.append(fn)
                            args = fn_obj.get("arguments", "")
                            output = (fn_obj.get("output", "") or "")[:5000]
                            log.warning(f"[{agent_key}] STEP {fn}: args={args[:200] if args else '(empty)'} | output={output[:200] if output else '(empty)'}")
                            query_trace.append(ToolTrace(
                                tool=fn,
                                arguments=args,
                                output=output,
                            ))

            if not answer:
                raise HTTPException(504, "Agent did not produce an answer")

            followUps = _generate_followups(agent_key, req.message, answer)
            log.warning(f"[{agent_key}] DONE. len={len(answer)}, steps={steps}, followUps={len(followUps)}")
            return ChatResponse(answer=answer, steps=steps, queryTrace=query_trace, followUps=followUps)

        finally:
            try:
                await client.delete(
                    f"{base}/threads/{thread_id}",
                    headers=fabric_headers(), params=params,
                )
            except Exception:
                pass


# ── Power BI Embed (user-owns-data) ──────────────────────────
@app.get("/api/embed-token")
async def embed_token():
    """Get report embed URL and user's PBI access token."""
    async with httpx.AsyncClient(timeout=30) as client:
        report_resp = await client.get(
            f"{PBI_BASE}/groups/{WORKSPACE_ID}/reports/{REPORT_ID}",
            headers=pbi_headers(),
        )
        if report_resp.status_code != 200:
            raise HTTPException(502, f"Report fetch failed: {report_resp.status_code}")
        embed_url = report_resp.json().get("embedUrl", "")
        # Extract tenant ID from token claims
        token = pbi_token()
        try:
            payload = token.split(".")[1]
            payload += "=" * (-len(payload) % 4)  # pad base64
            claims = json.loads(base64.urlsafe_b64decode(payload))
            tenant_id = claims.get("tid", "")
        except Exception:
            tenant_id = ""
        return {
            "token": token,
            "tokenType": "Aad",
            "embedUrl": embed_url,
            "reportId": REPORT_ID,
            "tenantId": tenant_id,
        }


# ── Live venue floor-plan heat map (portal-native RTI over Eventhouse) ─
@app.get("/api/floorplan")
async def floorplan():
    """Per-zone live + peak crowding metrics for the SVG venue heat map,
    plus latest/peak gate wait times. Queries the Eventhouse directly."""
    zones_q = """
    telemetry_kpi
    | where kpi_name in ('occupancy_pct','density_index','people_count','comfort_index')
    | join kind=inner (telemetry_kpi | summarize maxts = max(timestamp) by zone_id) on zone_id
    | where timestamp == maxts
    | summarize occupancy = round(avgif(value, kpi_name == 'occupancy_pct'), 1),
                density   = round(avgif(value, kpi_name == 'density_index'), 2),
                people    = round(avgif(value, kpi_name == 'people_count'), 0),
                comfort   = round(avgif(value, kpi_name == 'comfort_index'), 1)
      by zone_id
    | join kind=leftouter (
        telemetry_kpi
        | summarize peak_occupancy = round(maxif(value, kpi_name == 'occupancy_pct'), 1),
                    peak_density   = round(maxif(value, kpi_name == 'density_index'), 2),
                    peak_people    = round(maxif(value, kpi_name == 'people_count'), 0),
                    min_comfort    = round(minif(value, kpi_name == 'comfort_index'), 1)
          by zone_id
      ) on zone_id
    | project zone_id, occupancy, density, people, comfort,
              peak_occupancy, peak_density, peak_people, min_comfort
    """
    gates_q = """
    telemetry_queue
    | summarize arg_max(timestamp, wait_time_s) by gate_id
    | project gate_id, wait_min = round(wait_time_s / 60.0, 1)
    | join kind=leftouter (
        telemetry_queue | summarize peak_wait_min = round(max(wait_time_s) / 60.0, 1) by gate_id
      ) on gate_id
    | project gate_id, wait_min, peak_wait_min
    """
    asof_q = "telemetry_kpi | summarize m = max(timestamp) | project asOf = tostring(m)"
    zones = await kusto_query(zones_q)
    gates = await kusto_query(gates_q)
    asof = await kusto_query(asof_q)
    return {"zones": zones, "gates": gates,
            "asOf": (asof[0].get("asOf") if asof else None),
            "eventhouse": EVENTHOUSE_DB}


# ── Health ───────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "workspace": WORKSPACE_ID,
        "agents": {k: v["name"] for k, v in AGENTS.items()},
    }
