#!/usr/bin/env python3
"""
One-shot idempotent orchestrator for the Network Operations (NOA) demo.

Runs every deploy step in the correct, dependency-safe order. Each step is
idempotent (reuses items via state.json), so this is safe to re-run; it resumes
rather than duplicating. Finishes with a warm-up so the first live demo query
(Fabric auth + Kusto cold start from idle capacity) is paid for off-stage.

USAGE
  python deploy_all.py                    # full deploy, then warm-up
  python deploy_all.py --from ontology    # resume from a given step to the end
  python deploy_all.py ontology graph     # run only these steps (canonical order)
  python deploy_all.py --skip data_activator,kql_dashboard
  python deploy_all.py --warmup           # warm-up only (no deploy)
  python deploy_all.py --no-warmup        # deploy only

TENANT: az silently flips to another tenant. Set `az_subscription` in config.yaml
(the Azure subscription display name, e.g. "My-Fabric-Subscription") and this script runs
`az account set` first. Without it you get 404 EntityNotFound on the wrong tenant.
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

import argparse
import importlib
import subprocess
import time
import requests
from helpers import (load_config, load_state, get_fabric_token, fabric_headers,
                     get_kusto_token, print_step)

# Canonical deploy order (name -> module). Each module exposes main().
STEPS = [
    ("generate_data",          "generate_data"),
    ("workspace",              "deploy_workspace"),
    ("lakehouse",              "deploy_lakehouse"),
    ("setup_notebook",         "deploy_setup_notebook"),
    ("eventhouse",             "deploy_eventhouse"),
    ("preload_telemetry",      "preload_telemetry"),
    ("ontology",               "deploy_ontology"),
    ("graph",                  "deploy_graph"),
    ("kql_dashboard",          "deploy_kql_dashboard"),
    ("data_activator",         "deploy_data_activator"),
    ("operations_agent",       "deploy_operations_agent"),
    ("kql_shortcuts",          "deploy_kql_shortcuts"),
    ("semantic_model",         "deploy_semantic_model"),
    ("data_agent",             "deploy_data_agent"),
    ("report",                 "deploy_report"),
]
STEP_NAMES = [name for name, _ in STEPS]


def ensure_tenant(cfg):
    """Pin az to the right subscription/tenant (az silently flips to corp)."""
    sub = cfg.get("az_subscription")
    if not sub:
        print("⚠  No 'az_subscription' in config.yaml — ensure az is on the correct tenant "
              "(404 EntityNotFound = wrong tenant).")
        return
    try:
        subprocess.check_call(["az", "account", "set", "--subscription", sub], shell=True)
        print(f"✓  az subscription set to '{sub}'")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Could not set az subscription '{sub}': {e}")


def select_steps(args):
    if args.steps:
        unknown = [s for s in args.steps if s not in STEP_NAMES]
        if unknown:
            raise SystemExit(f"Unknown step(s): {unknown}. Valid: {STEP_NAMES}")
        chosen = [s for s in STEP_NAMES if s in args.steps]  # keep canonical order
    elif args.from_step:
        if args.from_step not in STEP_NAMES:
            raise SystemExit(f"Unknown --from step '{args.from_step}'. Valid: {STEP_NAMES}")
        i = STEP_NAMES.index(args.from_step)
        chosen = STEP_NAMES[i:]
    else:
        chosen = list(STEP_NAMES)
    skip = set(s.strip() for s in (args.skip or "").split(",") if s.strip())
    return [s for s in chosen if s not in skip]


def run_steps(names):
    mod_of = dict(STEPS)
    total = len(names)
    for idx, name in enumerate(names, 1):
        print_step(idx, total, f"STEP: {name}  (module {mod_of[name]})")
        mod = importlib.import_module(mod_of[name])
        mod.main()
    print(f"\n✓  {total} step(s) completed.")


def warm_up(cfg, state):
    """Pay the first-query latency off-stage: Fabric auth + Kusto cold start."""
    print_step(1, 2, "Warm-up: Fabric workspace + token")
    try:
        api = cfg["fabric_api_base"]; ws = state["workspace_id"]
        h = fabric_headers(get_fabric_token())
        items = requests.get(f"{api}/workspaces/{ws}/items", headers=h, timeout=60).json().get("value", [])
        print(f"   Fabric OK — {len(items)} items in workspace.")
    except Exception as e:
        print(f"   (warm-up Fabric skipped: {e})")

    print_step(2, 2, "Warm-up: Eventhouse/KQL query (cold start)")
    try:
        quri = state["query_service_uri"]; db = cfg["eventhouse_name"]
        ktok = get_kusto_token(quri)
        t0 = time.time()
        r = requests.post(f"{quri}/v1/rest/query",
                          headers={"Authorization": f"Bearer {ktok}",
                                   "Content-Type": "application/json; charset=utf-8"},
                          json={"db": db, "csl": "telemetry_env | where timestamp > ago(20m) | summarize maxT=max(temperature_c), hot=dcountif(container_id, temperature_c > 60)"}, timeout=120)
        r.raise_for_status()
        rows = r.json().get("Tables", [{}])[0].get("Rows", [[None, None]])
        print(f"   Kusto OK — recent max temperature_c={rows[0][0]} on {rows[0][1]} container(s) > 60C (fire risk) in {time.time()-t0:.1f}s.")
    except Exception as e:
        print(f"   (warm-up Kusto skipped: {e})")


def main():
    p = argparse.ArgumentParser(description="NOA deploy orchestrator")
    p.add_argument("steps", nargs="*", help=f"run only these steps (order fixed). Valid: {STEP_NAMES}")
    p.add_argument("--from", dest="from_step", help="resume from this step to the end")
    p.add_argument("--skip", help="comma-separated steps to skip")
    p.add_argument("--warmup", action="store_true", help="run warm-up only (no deploy)")
    p.add_argument("--no-warmup", dest="no_warmup", action="store_true", help="deploy without warm-up")
    args = p.parse_args()

    cfg = load_config()
    ensure_tenant(cfg)

    if args.warmup:
        warm_up(cfg, load_state())
        return

    names = select_steps(args)
    print(f"Plan: {names}")
    run_steps(names)

    if not args.no_warmup:
        warm_up(cfg, load_state())

    print("\n🎯  NOA ready. Demo: inject_event.py (live PFC storm) → Operations Agent alert → "
          "Data Agent RCA/impact (3 VIP).")


if __name__ == "__main__":
    main()
