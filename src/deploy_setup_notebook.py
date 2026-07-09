#!/usr/bin/env python3
"""
Deploy + run NB_Setup_Network — converts the uploaded topology CSVs (Files/raw/*.csv)
into Delta tables in the Lakehouse. Telemetry is NOT here (it goes to the Eventhouse).
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
sys.path.insert(0, str(Path(__file__).parent))
from helpers import load_config, load_state, save_state, get_fabric_token, print_step
from notebook_utils import recreate_notebook, run_notebook

NOTEBOOK_NAME = "NB_Setup_Waste"
RAW = Path(__file__).parent.parent / "data" / "raw"


def build_notebook_py(ws_id, lh_id, lh_name, tables):
    tables_list = ", ".join(f'"{t}"' for t in tables)
    return f'''# Fabric notebook source

# METADATA ********************

# META {{
# META   "kernel_info": {{
# META     "name": "synapse_pyspark"
# META   }},
# META   "dependencies": {{
# META     "lakehouse": {{
# META       "default_lakehouse": "{lh_id}",
# META       "default_lakehouse_name": "{lh_name}",
# META       "default_lakehouse_workspace_id": "{ws_id}"
# META     }}
# META   }}
# META }}

# MARKDOWN ********************

# # NB_Setup_Network — CSV (Files/raw) -> Delta tables (topology)

# CELL ********************

tables = [{tables_list}]
created = []
for t in tables:
    df = spark.read.csv(f"Files/raw/{{t}}.csv", header=True, inferSchema=True)
    df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(t)
    n = df.count()
    created.append((t, n))
    print(f"{{t}}: {{n}} rows")

print("DONE", created)
'''


def main():
    cfg = load_config(); state = load_state()
    ws = state["workspace_id"]; lh = state["lakehouse_id"]; lh_name = cfg["lakehouse_name"]
    token = get_fabric_token()

    print_step(1, 3, f"Build + (re)create notebook '{NOTEBOOK_NAME}'")
    telemetry = {t["name"] for t in cfg["kql_tables"].values()}
    tables = sorted(p.stem for p in RAW.glob("*.csv") if p.stem not in telemetry)
    py = build_notebook_py(ws, lh, lh_name, tables)
    nb_id = recreate_notebook(ws, NOTEBOOK_NAME, py, token)
    print(f"   notebook_id = {nb_id}")

    print_step(2, 3, "Run notebook (Spark cold start ~60-90s)")
    run_notebook(ws, nb_id, token, max_wait=900, poll_interval=20)
    print("   notebook completed")

    print_step(3, 3, "Persist state")
    state["notebook_setup_id"] = nb_id
    save_state(state)
    print(f"   saved notebook_setup_id")
    print("\nOK. Delta topology tables created.")


if __name__ == "__main__":
    main()
