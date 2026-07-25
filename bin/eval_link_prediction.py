#!/usr/bin/env python3
"""Score the network embedding on held-out link prediction (build seq: network embed).

The soft-retrieval counterpart to eval_network.py. It reads the leakage-free gold from
build_link_gold.py and the embedding retrained on the held-out graph
(data/network_lp.duckdb), and asks: for each removed disease<->target edge, does the
disease's structural neighbourhood still rank the target it was NOT trained to connect
to? Because the model never saw the edge, a hit is genuine prediction, not recall of a
memorised adjacency — the thing the question-gold cannot measure.

No SapBERT here: the anchor is a known disease node id, not a question, so this scores
the structural space alone. A single target per case, so recall@N is a hit-rate.

    eval_link_prediction.py --net data/network_lp.duckdb [--dim 128]
"""

import argparse
import json
import pathlib

import duckdb

import shape_common as sc
from eval_network import BUDGETS, mean, nearest

GOLD = sc.PROJECT_HOME / "eval" / "gold_link_prediction.jsonl"
NET_CONFIG = sc.PROJECT_HOME / "config" / "network_embed.yaml"


def main():
    import yaml

    ap = argparse.ArgumentParser(description="Score held-out link prediction.")
    ap.add_argument("--net", default=str(sc.PROJECT_HOME / "data" / "network_lp.duckdb"))
    ap.add_argument("--dim", type=int, help="vector dim (default: from config)")
    args = ap.parse_args()

    net_db = pathlib.Path(args.net)
    if not net_db.exists():
        raise SystemExit(f"{net_db} not found — run build_link_gold.py then "
                         f"embed_network.py --graph data/graph_lp.duckdb --out {net_db}")
    if not GOLD.exists():
        raise SystemExit(f"{GOLD} not found — run bin/build_link_gold.py first")
    dim = args.dim or yaml.safe_load(NET_CONFIG.read_text())["dim"]

    cases = [json.loads(x) for x in GOLD.read_text().splitlines() if x.strip()]
    net = duckdb.connect(str(net_db), read_only=True)
    maxn = max(BUDGETS)

    embedded = {r[0] for r in net.execute("SELECT id FROM node_vectors").fetchall()}
    for case in cases:
        # coverage: both endpoints must have survived into the embedding to be scorable
        case["_scorable"] = case["source"] in embedded and case["target"] in embedded
        ranked = nearest(net, case["source"], dim, maxn) if case["source"] in embedded else []
        for n in BUDGETS:
            case[f"_hit@{n}"] = float(case["target"] in ranked[:n])

    scorable = [c for c in cases if c["_scorable"]]
    print(f"link prediction (held-out edges), {len(cases)} edges, "
          f"{len(scorable)} scorable\n")
    hdr = "".join(f"{'hit@' + str(n):>10}" for n in BUDGETS)
    print(f"{'type':12} {'n':>4}{hdr}")
    for t in ["phenotype", "gene", "overall"]:
        group = scorable if t == "overall" else [c for c in scorable if c["type"] == t]
        hits = "".join(f"{mean([c[f'_hit@{n}'] for c in group]):>10.3f}" for n in BUDGETS)
        print(f"{t:12} {len(group):>4}{hits}")


if __name__ == "__main__":
    main()
