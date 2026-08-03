#!/usr/bin/env python3
"""
Inject LIVE event telemetry into the Eventhouse, timestamped at 'now', so the
Real-Time dashboard + the portal floor-plan heat map animate during a demo.

Two modes:
  • one-shot (default):  a single fresh batch (all zones + gates), culprit gate saturated.
  • loop (--loop):       keeps injecting every --interval seconds. The culprit access gate
                         (config: culprit_gate) ramps from calm to full congestion over
                         --ramp cycles, then holds — you watch Salle Aspen turn red live.

Every tick writes, for EVERY zone: occupancy / people / density / m2-utilization / comfort,
plus a queue row per gate. The culprit gate/zone is scaled by the current intensity, and a
Critical CONGESTION alarm + event log fire once it crosses the threshold.

  python inject_event.py                 # one saturated snapshot now
  python inject_event.py --loop          # animate (Ctrl+C to stop), 15s ticks, 8-cycle ramp
  python inject_event.py --loop --interval 10 --ramp 6 --cycles 40
"""
import sys, argparse, time
from platform_env import bootstrap
bootstrap()

from pathlib import Path
from datetime import datetime, timezone
import random
import pandas as pd
from helpers import load_config, load_state, get_kusto_token, kusto_mgmt, print_step

RAW = Path(__file__).parent.parent / "data" / "raw"
CONGESTION_THRESHOLD_S = 600  # 10 min — Ops Agent congestion rule


def _lerp(a, b, t):
    return a + (b - a) * t


def build_tick(cfg, zones, culprit, intensity, rng):
    """Build one timestamped batch (all zones + gates). Culprit scaled by `intensity` (0..1)."""
    kpi_names = cfg["telemetry"]["kpi_names"]
    cap_of = dict(zip(zones["zone_id"], zones["capacity"]))
    gate_of = dict(zip(zones["zone_id"], zones["served_by_gate"]))
    now = datetime.now(timezone.utc).replace(microsecond=0)
    iso = now.isoformat()

    queue, kpi, alarms, logs = [], [], [], []
    culprit_wait = 0.0
    for zid in zones["zone_id"].tolist():
        gate = gate_of.get(zid, "")
        cap = int(cap_of.get(zid, 500))
        is_culprit = (gate == culprit)

        if is_culprit:
            occ = _lerp(rng.uniform(55, 68), rng.uniform(95, 100), intensity)
            den = _lerp(rng.uniform(2.0, 3.0), rng.uniform(4.5, 6.5), intensity)
            comfort = _lerp(rng.uniform(60, 72), rng.uniform(18, 32), intensity)
            util = _lerp(rng.uniform(60, 75), rng.uniform(95, 100), intensity)
            wait = _lerp(rng.uniform(90, 240), rng.uniform(900, 1600), intensity)
        else:
            occ = rng.uniform(38, 82)
            den = rng.uniform(1.4, 3.6)
            comfort = rng.uniform(55, 82)
            util = rng.uniform(45, 85)
            wait = rng.uniform(45, 320)

        vals = {"occupancy_pct": round(occ, 1),
                "people_count": round(occ / 100 * cap * rng.uniform(0.95, 1.12), 0),
                "density_index": round(den, 2),
                "utilization_m2_pct": round(min(util, 100.0), 1),
                "comfort_index": round(comfort, 1)}
        for kn in kpi_names:
            kpi.append(f"{iso},{zid},{gate},{kn},{vals[kn]}")
        queue.append(f"{iso},{gate},{zid},{round(wait,1)},{rng.randint(40,200)},{rng.randint(20,90)}")
        if is_culprit:
            culprit_wait = wait

    if culprit_wait >= CONGESTION_THRESHOLD_S:
        alarms.append(f"{iso},{culprit},CONGESTION,Critical,raised")
        logs.append(f'{iso},{culprit},ERR,"Crowd control: security queue above 15 minutes at Aspen gate"')
    return now, queue, kpi, alarms, logs, culprit_wait


def ingest(quri, ktok, db, batches):
    for table, rows in batches:
        if rows:
            kusto_mgmt(quri, ktok, db, f".ingest inline into table {table} <|\n" + "\n".join(rows))


def main():
    ap = argparse.ArgumentParser(description="Inject live event telemetry.")
    ap.add_argument("--loop", action="store_true", help="Keep injecting every --interval seconds.")
    ap.add_argument("--interval", type=float, default=15.0, help="Seconds between ticks (loop mode).")
    ap.add_argument("--ramp", type=int, default=8, help="Cycles to ramp the culprit gate to full congestion.")
    ap.add_argument("--cycles", type=int, default=0, help="Total ticks in loop mode (0 = infinite).")
    args = ap.parse_args()

    cfg = load_config(); state = load_state()
    db = cfg["eventhouse_name"]; quri = state["query_service_uri"]
    culprit = cfg["culprit_gate"]
    ktok = get_kusto_token(quri)
    rng = random.Random()
    zones = pd.read_csv(RAW / "dim_zones.csv")

    if not args.loop:
        now, q, k, a, l, cw = build_tick(cfg, zones, culprit, intensity=1.0, rng=rng)
        print_step(1, 1, f"Inject saturated snapshot on {culprit} @ {now.isoformat()}")
        ingest(quri, ktok, db, [("telemetry_queue", q), ("telemetry_kpi", k), ("alarms", a), ("event_logs", l)])
        print(f"   all zones + gates refreshed · {culprit} wait {cw/60:.1f} min (saturated)")
        print("\nSnapshot injected. Watch the portal 'Temps Réel' floor plan (Live mode).")
        return

    print(f"LIVE injector: every {args.interval:.0f}s, ramp over {args.ramp} cycles, "
          f"{'infinite' if not args.cycles else args.cycles} ticks. Ctrl+C to stop.\n")
    tick = 0
    try:
        while True:
            tick += 1
            intensity = min(1.0, tick / max(1, args.ramp))
            now, q, k, a, l, cw = build_tick(cfg, zones, culprit, intensity, rng)
            ingest(quri, ktok, db, [("telemetry_queue", q), ("telemetry_kpi", k), ("alarms", a), ("event_logs", l)])
            filled = int(intensity * 20)
            bar = "█" * filled + "·" * (20 - filled)
            flag = "  ⚠ CONGESTION" if cw >= CONGESTION_THRESHOLD_S else ""
            print(f"[tick {tick:>3}] {now.strftime('%H:%M:%S')}  {bar}  {culprit} wait {cw/60:5.1f} min{flag}")
            if args.cycles and tick >= args.cycles:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")
    print(f"\nDone ({tick} ticks). The Eventhouse now holds a live congestion peak on {culprit}.")


if __name__ == "__main__":
    main()
