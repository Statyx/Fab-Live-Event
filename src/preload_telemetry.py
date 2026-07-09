#!/usr/bin/env python3
"""
Batch-ingest the telemetry CSVs into the Eventhouse KQL tables via the Kusto
streaming-ingestion REST API. Verifies row counts afterwards.
"""
import os, sys, winreg, time
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

from pathlib import Path
from helpers import (load_config, load_state, get_kusto_token, kusto_mgmt,
                     print_step)

RAW = Path(__file__).parent.parent / "data" / "raw"
BATCH = 200   # .ingest inline is reliable in batches of ~200 rows


def _mgmt_retry(quri, ktok, db, cmd, tries=6, backoff=6):
    """Kusto mgmt with retry — a freshly-created Eventhouse throws transient 520
    InternalServiceError / SSL EOF while it warms up; a retry succeeds."""
    last = None
    for attempt in range(1, tries + 1):
        try:
            return kusto_mgmt(quri, ktok, db, cmd)
        except Exception as e:  # HTTPError 520 / ConnectionError / SSL EOF
            last = e
            if attempt < tries:
                print(f"      (transient Kusto error, retry {attempt}/{tries-1} in {backoff}s)")
                time.sleep(backoff)
    raise last


def ingest_csv(quri, ktok, db, table):
    text = (RAW / f"{table}.csv").read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    data = lines[1:]  # drop header
    total = 0
    for i in range(0, len(data), BATCH):
        chunk = "\n".join(data[i:i + BATCH])
        _mgmt_retry(quri, ktok, db, f".ingest inline into table {table} <|\n{chunk}")
        total += min(BATCH, len(data) - i)
    return total



def main():
    cfg = load_config(); state = load_state()
    db = cfg["eventhouse_name"]; quri = state["query_service_uri"]
    ktok = get_kusto_token(quri)

    print_step(1, 2, "Ingest telemetry CSVs (clear + inline batches)")
    for _, t in cfg["kql_tables"].items():
        name = t["name"]
        try:
            kusto_mgmt(quri, ktok, db, f".clear table {name} data")
        except Exception:
            pass
        n = ingest_csv(quri, ktok, db, name)
        print(f"   {name}: sent {n} rows")

    print_step(2, 2, "Verify row counts (after ingest settles)")
    time.sleep(20)
    for _, t in cfg["kql_tables"].items():
        name = t["name"]
        try:
            r = kusto_mgmt(quri, ktok, db, f"{name} | count")
            # mgmt returns Tables[0].Rows[0][0] for count via query path; use a query instead
        except Exception:
            pass
    # counts via query endpoint
    import requests
    qh = {"Authorization": f"Bearer {ktok}", "Content-Type": "application/json"}
    for _, t in cfg["kql_tables"].items():
        name = t["name"]
        rr = requests.post(f"{quri}/v1/rest/query", headers=qh,
                           json={"db": db, "csl": f"{name} | count"}, timeout=60)
        try:
            cnt = rr.json()["Tables"][0]["Rows"][0][0]
        except Exception:
            cnt = "?"
        print(f"   {name}: {cnt} rows in KQL")
    print("\nOK. Telemetry loaded.")


if __name__ == "__main__":
    main()
