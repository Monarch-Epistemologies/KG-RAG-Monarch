#!/usr/bin/env python3
"""Score the network (structural) embedding on the gold (build seq: network embed).

The third method's column, beside node-text / triple-text retrieval and the crawler.
Runs under the MAIN venv: it needs SapBERT (sentence-transformers) for the anchor and
reads the structural vectors that bin/embed_network.py wrote (under venv313) into
data/network.duckdb.

The pipeline is deliberately the minimal one — this is what the structural space alone
buys, with none of the crawler's predicate machinery:

  anchor   — SapBERT maps the question to its nearest MONDO node (reused unchanged from
             the crawler's front door: bin/anchor.py).
  retrieve — return that node's nearest neighbours IN THE STRUCTURAL SPACE. No predicate
             classifier, no edge-count disambiguation, no SQL traversal: one cosine
             lookup over data/network.duckdb.

Unlike SQL traversal (which returns *every* true neighbour, so recall is uncapped), a
nearest-neighbour lookup is ranked and needs a budget N. Recall is therefore reported at
several N so the trade — structural similarity is lossy vs. exact adjacency — is visible.

    eval_network.py [--device cpu]
"""

import argparse
import json
import pathlib

import duckdb
import yaml

import shape_common as sc
from anchor import DB as SAP_DB
from anchor import MODEL, anchor
from embed_models import build_model

GOLD = sc.PROJECT_HOME / "eval" / "gold_monarch.jsonl"
NET_DB = sc.PROJECT_HOME / "data" / "network.duckdb"
NET_CONFIG = sc.PROJECT_HOME / "config" / "network_embed.yaml"
ANCHOR_PREFIX = "MONDO:"
BUDGETS = [20, 100, 250]  # recall@N; 20 matches node/triple's k for an apples-to-apples column


def pick_anchor(candidates):
    """First SapBERT candidate in the disease namespace, else the top hit. This is the
    anchor WITHOUT the crawler's edge-count disambiguation — the minimal front door."""
    if not candidates:
        return None
    for cand in candidates:
        if cand[0].startswith(ANCHOR_PREFIX):
            return cand[0]
    return candidates[0][0]


def nearest(net, anchor_id, dim, budget):
    """The anchor node's `budget` nearest neighbours in the structural space, itself
    excluded. Empty if the anchor has no structural vector (e.g. it had no edges)."""
    row = net.execute(
        "SELECT embedding FROM node_vectors WHERE id = ?", [anchor_id]
    ).fetchone()
    if row is None:
        return []
    return [
        r[0]
        for r in net.execute(
            f"""SELECT id, array_cosine_similarity(embedding, ?::FLOAT[{dim}]) AS sim
                FROM node_vectors WHERE id <> ?
                ORDER BY sim DESC LIMIT ?""",
            [row[0], anchor_id, budget],
        ).fetchall()
    ]


def score_cases(net, sap, model, cases, dim, budgets):
    """Populate each case with _anchor_hit and _recall@n for every n in budgets, in
    place, and return the cases. Shared by main() and the knob sweep (sweep_network.py)."""
    maxn = max(budgets)
    for case in cases:
        anchor_id = pick_anchor(anchor(sap, model, case["question"]))
        case["_anchor_hit"] = float(anchor_id == case["anchor"])
        ranked = nearest(net, anchor_id, dim, maxn) if anchor_id else []
        answers = set(case["answer_entities"])
        for n in budgets:
            hit = answers & set(ranked[:n])
            case[f"_recall@{n}"] = len(hit) / len(answers) if answers else 0.0
    return cases


def mean(vals):
    return sum(vals) / len(vals) if vals else 0.0


def main():
    ap = argparse.ArgumentParser(description="Score the structural embedding.")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--net", default=str(NET_DB), help="vectors .duckdb to score")
    ap.add_argument("--dim", type=int, help="vector dim (default: from config)")
    args = ap.parse_args()

    net_db = pathlib.Path(args.net)
    if not net_db.exists():
        raise SystemExit(f"{net_db} not found — run bin/embed_network.py (venv313) first")
    dim = args.dim or yaml.safe_load(NET_CONFIG.read_text())["dim"]

    cases = [json.loads(x) for x in GOLD.read_text().splitlines() if x.strip()]
    model = build_model(MODEL, device=args.device)
    sap = duckdb.connect(str(SAP_DB), read_only=True)
    net = duckdb.connect(str(net_db), read_only=True)
    score_cases(net, sap, model, cases, dim, BUDGETS)

    print(f"network embedding ({net_db.name}), {len(cases)} questions\n")
    hdr = "".join(f"{'recall@' + str(n):>11}" for n in BUDGETS)
    print(f"{'type':12} {'n':>3}{hdr} {'anchor-acc':>11}")
    for t in ["phenotype", "gene", "treatment", "overall"]:
        group = cases if t == "overall" else [c for c in cases if c["type"] == t]
        recalls = "".join(
            f"{mean([c[f'_recall@{n}'] for c in group]):>11.3f}" for n in BUDGETS
        )
        print(
            f"{t:12} {len(group):>3}{recalls} "
            f"{mean([c['_anchor_hit'] for c in group]):>11.3f}"
        )


if __name__ == "__main__":
    main()
