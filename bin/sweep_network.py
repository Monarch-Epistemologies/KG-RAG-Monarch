#!/usr/bin/env python3
"""Sweep the network embedding's build knobs and score each on the gold (build seq:
network embed, tuning track).

For each point in a small grid of overrides (dim / walk_length / num_walks / scheme),
rebuild the embedding and score it, so the effect of each knob on recall is a table
rather than a guess. This is tuning, not a new method — its only product is which config
the reported "network" column should use.

It spans both interpreters, like the rest of the network-embedding line: each build runs
under venv313 (gensim) as a subprocess writing a temp .duckdb; the scoring runs here in
the main venv (SapBERT), reusing eval_network.score_cases. Builds are ~10-15 min each, so
the grid is deliberately short — widen GRID for an overnight run.

    sweep_network.py [--device cpu]
"""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

import duckdb
import yaml

import shape_common as sc
from anchor import DB as SAP_DB
from anchor import MODEL, anchor  # noqa: F401  (anchor used via score_cases)
from embed_models import build_model
from eval_network import BUDGETS, mean, score_cases

VENV313_PY = sc.PROJECT_HOME / "venv313" / "bin" / "python3"
EMBED = sc.PROJECT_HOME / "bin" / "embed_network.py"
BASE_CONFIG = sc.PROJECT_HOME / "config" / "network_embed.yaml"
GOLD = sc.PROJECT_HOME / "eval" / "gold_monarch.jsonl"

# The grid: each entry is a set of overrides on the base config. Metapath builds are
# cheap (~1 min), so these run in a few minutes; the uniform baseline (a ~15 min build)
# is measured separately and left out here. Widen for a patient overnight sweep.
GRID = [
    {"scheme": "metapath"},                      # the reported config
    {"scheme": "metapath", "num_walks": 20},     # more walks per node
    {"scheme": "metapath", "walk_length": 80},   # longer walks
    {"scheme": "metapath", "dim": 256},          # bigger vectors
]


def build_one(overrides, tmp):
    """Write a temp config with the overrides applied, run the venv313 build to a temp
    .duckdb, and return (db_path, dim). Raises if the subprocess fails."""
    cfg = yaml.safe_load(BASE_CONFIG.read_text())
    scheme = overrides.pop("scheme", cfg.get("walk_scheme", "uniform"))
    cfg.update(overrides)
    cfg_path = tmp / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg))
    db = tmp / "vectors.duckdb"
    if db.exists():
        db.unlink()
    subprocess.run(
        [str(VENV313_PY), str(EMBED), "--config", str(cfg_path),
         "--out", str(db), "--scheme", scheme],
        check=True,
    )
    return db, cfg["dim"]


def main():
    ap = argparse.ArgumentParser(description="Sweep network-embedding build knobs.")
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()

    cases_template = [json.loads(x) for x in GOLD.read_text().splitlines() if x.strip()]
    model = build_model(MODEL, device=args.device)
    sap = duckdb.connect(str(SAP_DB), read_only=True)

    hdr = "".join(f"{'recall@' + str(n):>11}" for n in BUDGETS)
    print(f"{'config':40}{hdr} {'anchor-acc':>11}")
    for point in GRID:
        label = ", ".join(f"{k}={v}" for k, v in point.items())
        with tempfile.TemporaryDirectory() as td:
            db, dim = build_one(dict(point), Path(td))
            net = duckdb.connect(str(db), read_only=True)
            cases = [dict(c) for c in cases_template]  # fresh copy per point
            score_cases(net, sap, model, cases, dim, BUDGETS)
            net.close()
        recalls = "".join(
            f"{mean([c[f'_recall@{n}'] for c in cases]):>11.3f}" for n in BUDGETS
        )
        anchor_acc = mean([c["_anchor_hit"] for c in cases])
        print(f"{label:40}{recalls} {anchor_acc:>11.3f}")


if __name__ == "__main__":
    main()
