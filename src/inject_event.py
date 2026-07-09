#!/usr/bin/env python3
"""
Inject a LIVE congestion peak on the culprit access gate (config: culprit_gate) into the
Eventhouse, timestamped at 'now'. Use during the demo for the real-time moment:
  - queue wait-time spike (security bottleneck) on the culprit gate
  - occupancy / density saturation + comfort drop on the zone it serves
  - a Critical CONGESTION alarm + an event log line
Data Activator (if configured) fires on this; the Operations Agent sees a current anomaly.

Idempotent-ish: just appends current-time rows (run again for a fresh peak).
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

from pathlib import Path
from datetime import datetime, timedelta, timezone
import random
import pandas as pd
from helpers import load_config, load_state, get_kusto_token, kusto_mgmt, print_step

RAW = Path(__file__).parent.parent / "data" / "raw"


def main():
    cfg = load_config(); state = load_state()
    db = cfg["eventhouse_name"]; quri = state["query_service_uri"]
    culprit = cfg["culprit_gate"]
    ktok = get_kusto_token(quri)
    rng = random.Random()

    zones = pd.read_csv(RAW / "dim_zones.csv")
    culprit_zones = zones[zones["served_by_gate"] == culprit]["zone_id"].tolist()
    cap_of = dict(zip(zones["zone_id"], zones["capacity"]))
    kpi_names = cfg["telemetry"]["kpi_names"]

    now = datetime.now(timezone.utc).replace(microsecond=0)
    stamps = [now - timedelta(minutes=2), now - timedelta(minutes=1), now]

    queue, kpi, alarms, logs = [], [], [], []
    for ts in stamps:
        iso = ts.isoformat()
        # gate queue spike
        z = culprit_zones[0] if culprit_zones else ""
        queue.append(f"{iso},{culprit},{z},{rng.uniform(900,1600):.1f},{rng.randint(120,200)},{rng.randint(20,50)}")
        # zone saturation KPIs
        for zid in culprit_zones:
            cap = int(cap_of.get(zid, 500))
            occ = rng.uniform(95, 100)
            vals = {"occupancy_pct": round(occ, 1), "people_count": round(occ/100*cap*rng.uniform(1.0, 1.15), 0),
                    "density_index": round(rng.uniform(4.5, 6.5), 2), "utilization_m2_pct": round(rng.uniform(95, 100), 1),
                    "comfort_index": round(rng.uniform(18, 32), 1)}
            for kn in kpi_names:
                kpi.append(f"{iso},{zid},{culprit},{kn},{vals[kn]}")
    alarms.append(f"{now.isoformat()},{culprit},CONGESTION,Critical,raised")
    logs.append(f'{now.isoformat()},{culprit},ERR,"Crowd control: security queue above 15 minutes at Aspen gate"')

    print_step(1, 1, f"Inject live congestion peak on {culprit} @ {now.isoformat()}")
    for table, rows in [("telemetry_queue", queue), ("telemetry_kpi", kpi), ("alarms", alarms), ("event_logs", logs)]:
        if not rows:
            continue
        kusto_mgmt(quri, ktok, db, f".ingest inline into table {table} <|\n" + "\n".join(rows))
        print(f"   {table}: +{len(rows)} rows")
    print(f"\nLive congestion peak injected on {culprit} (saturates {len(culprit_zones)} zone(s)). "
          f"Data Activator should fire; ask the Operations Agent what's happening now.")


if __name__ == "__main__":
    main()
