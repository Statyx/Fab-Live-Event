#!/usr/bin/env python3
"""
Generate synthetic Live Event (large-event) data for the LEO demo.

Produces:
  Topology (Lakehouse / NonTimeSeries) → data/raw/dim_*.csv, fact_observations.csv
  Telemetry (Eventhouse / TimeSeries)  → data/raw/telemetry_kpi.csv, telemetry_queue.csv,
                                         alarms.csv, event_logs.csv

The data embeds a scripted **congestion peak on the culprit access gate** (config:
culprit_gate) so the Operations Agent can do real RCA: the gate's queue wait-time spikes,
the zone it serves saturates (occupancy / density up, comfort down), which lights up the
flagship sessions and VIP sponsors in that zone.

Deterministic (seeded) — re-running yields the same data. Pure Python + pandas.
"""
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import random
import pandas as pd
import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).parent
ROOT = SCRIPT_DIR.parent
RAW = ROOT / "data" / "raw"
SEED = 42

OBS_CATEGORIES = ["Crowd", "Safety", "Cleanliness", "Technical", "Access"]


def load_config():
    """Load src/config.yaml, falling back to the committed src/config.example.yaml.

    The example holds the full synthetic topology, so the generator (and the offline
    test gate) works on a fresh clone before anyone copies the file.
    """
    path = SCRIPT_DIR / "config.yaml"
    if not path.exists():
        path = SCRIPT_DIR / "config.example.yaml"
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_topology(cfg):
    """Build the static event topology. Returns a dict of DataFrames."""
    ed = cfg["edition"]
    zones_cfg = cfg["zones"]
    culprit = cfg["culprit_gate"]  # e.g. GATE-05

    gates, zones, sensors = [], [], []
    # One turnstile access gate per zone, numbered globally so GATE-05 serves zone index 5.
    for i, z in enumerate(zones_cfg, start=1):
        zid = z["id"]
        gate = f"GATE-{i:02d}"
        gates.append({"gate_id": gate, "edition_id": ed["id"], "gate_type": "Turnstile",
                      "vendor": "Kudelski", "model": "SmartGate-X", "role": "Entry"})
        zones.append({"zone_id": zid, "name": z["name"], "edition_id": ed["id"], "served_by_gate": gate,
                      "room_type": z["room_type"], "surface_m2": z["surface_m2"],
                      "capacity": z["capacity"], "is_premium": bool(z["premium"]), "status": "open"})
        # sensors on each gate: 2 badge readers + 2 computer-vision cameras
        for p, kind in [(1, "BadgeReader"), (2, "BadgeReader"), (3, "CVCamera"), (4, "CVCamera")]:
            sensors.append({"sensor_id": f"{gate}-s{p}", "gate_id": gate, "name": kind,
                            "sample_rate_s": 5 if kind == "CVCamera" else 1, "admin_status": "up"})

    df_gates = pd.DataFrame(gates)
    df_zones = pd.DataFrame(zones)
    df_sensors = pd.DataFrame(sensors)
    df_editions = pd.DataFrame([{"edition_id": ed["id"], "edition_name": ed["name"],
                                 "venue": ed["venue"], "city": ed["city"], "edition_type": ed["edition_type"]}])

    df_customers = pd.DataFrame([{"customer_id": c["id"], "name": c["name"],
                                  "segment": c["segment"], "vip_flag": bool(c["vip"])}
                                 for c in cfg["customers"]])
    df_sessions = pd.DataFrame([{"session_id": s["id"], "zone_id": s["zone_id"], "name": s["name"],
                                 "capacity": s["capacity"], "track": s["track"], "sponsor_id": s["sponsor_id"]}
                                for s in cfg["sessions"]])

    # culprit gate -> the zone it serves (the saturated zone)
    culprit_idx = int(culprit.split("-")[-1])          # GATE-05 -> 5
    culprit_zone = zones_cfg[culprit_idx - 1]["id"]
    culprit_zones = df_zones[df_zones["served_by_gate"] == culprit]["zone_id"].tolist()

    # sponsorships: one booth per customer, located in the zone of their first session
    # (so VIP sponsors of Aspen sessions surface when Aspen saturates).
    first_zone = {}
    for s in cfg["sessions"]:
        first_zone.setdefault(s["sponsor_id"], s["zone_id"])
    sp_rows = []
    for c in cfg["customers"]:
        zid = first_zone.get(c["id"], df_zones["zone_id"].iloc[0])
        tier = "Platinum" if c["vip"] else "Silver"
        sp_rows.append({"sponsorship_id": f"SP-{c['id'][-3:]}", "name": f"{c['name']} Booth",
                        "package_tier": tier, "customer_id": c["id"], "zone_id": zid})
    df_sponsorships = pd.DataFrame(sp_rows)

    # Dalux field observations (H&S / incidents). Seed one crowd-safety obs in the culprit zone.
    rng = random.Random(SEED)
    obs_rows = [{"observation_id": "OBS-0001", "zone_id": culprit_zone, "category": "Crowd",
                 "severity": "High", "status": "Open", "opened_at": datetime(2026, 6, 23, 18, 5, tzinfo=timezone.utc).isoformat(),
                 "comment": "Dense crowd building at the entrance queue"}]
    for n in range(2, 11):
        zid = rng.choice(df_zones["zone_id"].tolist())
        obs_rows.append({
            "observation_id": f"OBS-{n:04d}", "zone_id": zid,
            "category": rng.choice(OBS_CATEGORIES),
            "severity": rng.choice(["Low", "Medium", "High"]),
            "status": rng.choice(["Open", "Closed", "Resolved"]),
            "opened_at": (datetime(2026, 6, 23, 8, tzinfo=timezone.utc) + timedelta(hours=n)).isoformat(),
            "comment": "Routine field observation",
        })
    df_observations = pd.DataFrame(obs_rows)

    return {
        "dim_editions": df_editions, "dim_zones": df_zones, "dim_gates": df_gates,
        "dim_sensors": df_sensors, "dim_sessions": df_sessions,
        "dim_customers": df_customers, "dim_sponsorships": df_sponsorships,
        "fact_observations": df_observations,
    }, {"culprit": culprit, "culprit_zone": culprit_zone, "culprit_zones": culprit_zones}


def build_telemetry(cfg, topo, meta):
    """Build time-series telemetry with an embedded congestion peak on the culprit gate."""
    t = cfg["telemetry"]
    window_h, step_min = t["window_hours"], t["interval_min"]
    storm_start = t["storm_start_min"]
    storm_end = storm_start + t["storm_duration_min"]
    kpi_names = t["kpi_names"]
    culprit, culprit_zones = meta["culprit"], set(meta["culprit_zones"])

    start = datetime(2026, 6, 23, 0, 0, tzinfo=timezone.utc)
    n_steps = int(window_h * 60 / step_min)
    times = [start + timedelta(minutes=step_min * k) for k in range(n_steps)]
    rng = random.Random(SEED + 1)

    cap_of = dict(zip(topo["dim_zones"]["zone_id"], topo["dim_zones"]["capacity"]))

    def in_storm(minute):
        return storm_start <= minute < storm_end

    # ── KPI per zone (long format) ──────────────────────────────────
    kpi_rows = []
    for _, zone in topo["dim_zones"].iterrows():
        zid = zone["zone_id"]; cap = max(1, int(zone["capacity"]))
        base_occ = rng.uniform(25, 55)          # % occupancy baseline
        impacted = zid in culprit_zones
        for k, ts in enumerate(times):
            minute = k * step_min
            # event ramps up over the day (peaks late afternoon), diurnal-ish
            ramp = math.sin(math.pi * min(1.0, (minute % 1440) / 1200))
            storm = in_storm(minute) and impacted
            occ = base_occ * (0.6 + 0.9 * ramp) + rng.gauss(0, 4)
            occ = max(0.0, min(100.0, occ))
            people = occ / 100 * cap
            density = max(0.0, people / max(1.0, zone["surface_m2"]) * 4 + rng.gauss(0, 0.2))
            util = min(100.0, occ * rng.uniform(0.85, 1.0))
            comfort = max(0.0, 100 - occ * 0.6 - density * 5 + rng.gauss(0, 3))
            if storm:
                occ = rng.uniform(95, 100)
                people = occ / 100 * cap * rng.uniform(1.0, 1.15)   # over capacity
                density = rng.uniform(4.5, 6.5)                     # crowd-safety risk
                util = rng.uniform(95, 100)
                comfort = rng.uniform(18, 32)                       # comfort collapses
            vals = {"occupancy_pct": round(occ, 1), "people_count": round(people, 0),
                    "density_index": round(density, 2), "utilization_m2_pct": round(util, 1),
                    "comfort_index": round(comfort, 1)}
            for kn in kpi_names:
                kpi_rows.append({"timestamp": ts.isoformat(), "zone_id": zid,
                                 "gate_id": zone["served_by_gate"], "kpi_name": kn, "value": vals[kn]})
    df_kpi = pd.DataFrame(kpi_rows)

    # ── Queue stats per gate ────────────────────────────────────────
    queue_rows = []
    for _, gate in topo["dim_gates"].iterrows():
        gid = gate["gate_id"]
        zid = topo["dim_zones"][topo["dim_zones"]["served_by_gate"] == gid]["zone_id"]
        zid = zid.iloc[0] if len(zid) else ""
        culprit_gate = gid == culprit
        for k, ts in enumerate(times):
            minute = k * step_min
            ramp = math.sin(math.pi * min(1.0, (minute % 1440) / 1200))
            wait = 30 + 150 * ramp + rng.gauss(0, 15)
            inflow = int(max(0, 40 * ramp + rng.gauss(0, 6)))
            outflow = int(max(0, 35 * ramp + rng.gauss(0, 6)))
            if in_storm(minute) and culprit_gate:
                wait = rng.uniform(900, 1600)       # 15-27 min queue (security bottleneck)
                inflow = int(rng.uniform(120, 200))
                outflow = int(rng.uniform(20, 50))
            queue_rows.append({"timestamp": ts.isoformat(), "gate_id": gid, "zone_id": zid,
                               "wait_time_s": round(max(0.0, wait), 1),
                               "in_count": int(inflow), "out_count": int(outflow)})
    df_queue = pd.DataFrame(queue_rows)

    # ── alarms + logs (congestion evidence on the culprit gate) ─────
    alarm_rows, log_rows = [], []
    for k, ts in enumerate(times):
        minute = k * step_min
        if minute == storm_start:
            alarm_rows.append({"timestamp": ts.isoformat(), "gate_id": culprit,
                               "alarm_type": "CONGESTION", "severity": "Critical", "state": "raised"})
            log_rows.append({"timestamp": ts.isoformat(), "gate_id": culprit, "severity": "ERR",
                             "message": "Crowd control: security queue above 15 minutes at Aspen gate"})
        if minute == storm_end:
            alarm_rows.append({"timestamp": ts.isoformat(), "gate_id": culprit,
                               "alarm_type": "CONGESTION", "severity": "Critical", "state": "cleared"})
            log_rows.append({"timestamp": ts.isoformat(), "gate_id": culprit, "severity": "INFO",
                             "message": "Crowd control: queue back to nominal at Aspen gate"})
    for n in range(6):
        g = rng.choice(topo["dim_gates"]["gate_id"].tolist())
        log_rows.append({"timestamp": times[n * 10].isoformat(), "gate_id": g,
                         "severity": "INFO", "message": "Gate counters polled"})
    df_alarms = pd.DataFrame(alarm_rows)
    df_logs = pd.DataFrame(log_rows)

    return {"telemetry_kpi": df_kpi, "telemetry_queue": df_queue,
            "alarms": df_alarms, "event_logs": df_logs}


def main():
    cfg = load_config()
    RAW.mkdir(parents=True, exist_ok=True)
    print("Generating live-event topology + telemetry...")
    topo, meta = build_topology(cfg)
    tele = build_telemetry(cfg, topo, meta)

    all_tables = {**topo, **tele}
    for name, df in all_tables.items():
        path = RAW / f"{name}.csv"
        df.to_csv(path, index=False, encoding="utf-8")
        print(f"   {name:24s} {len(df):>7d} rows -> {path.name}")

    print(f"\nCulprit gate: {meta['culprit']} -> saturates zone {meta['culprit_zone']} "
          f"({', '.join(meta['culprit_zones'])}).")
    print(f"Congestion window: minute {cfg['telemetry']['storm_start_min']}"
          f"-{cfg['telemetry']['storm_start_min'] + cfg['telemetry']['storm_duration_min']} "
          f"of a {cfg['telemetry']['window_hours']}h event day.")
    print("Done.")


if __name__ == "__main__":
    main()
