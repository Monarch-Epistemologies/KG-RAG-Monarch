#!/usr/bin/env python3
"""Score retrieval quality-in-context against the derived gold (build seq #3, eval).

For each gold question, embed it with the corpus's model, take the top-k nearest
nodes, and measure recall of the answer entities — the graph neighbours a real answer
needs. Reports per question type, because the types diverge: these are traversal-shaped
questions, so node-text retrieval (which ranks text-similar nodes, not graph neighbours)
is expected to score low. That low score is the baseline triple-text retrieval must
beat, and the gap is the nodes-vs-triples evidence.

Anchor recall is reported alongside as a sanity check: node retrieval should at least
surface the disease the question names, even when it misses that disease's neighbours.

    eval_score.py [-k 20] [--model ...]
"""

import argparse
import json

import duckdb
import numpy as np

import shape_common as sc
from embed_models import build_model

DEFAULT_MODEL = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"
GOLD = sc.PROJECT_HOME / "eval" / "gold_monarch.jsonl"
DB = sc.PROJECT_HOME / "data" / "embeddings.duckdb"


def main():
    ap = argparse.ArgumentParser(description="Score node retrieval against the gold.")
    ap.add_argument("-k", type=int, default=20)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()

    cases = [json.loads(line) for line in GOLD.read_text().splitlines() if line.strip()]

    # Load the whole node-vector table into memory once; 180 questions against 300k
    # nodes is far cheaper as one matrix product than as 180 DuckDB scans.
    con = duckdb.connect(str(DB), read_only=True)
    ids, vecs = [], []
    for node_id, emb in con.execute(
        "SELECT id, embedding FROM node_vectors"
    ).fetchall():
        ids.append(node_id)
        vecs.append(emb)
    gallery = np.asarray(vecs, dtype=np.float32)
    gallery /= np.linalg.norm(gallery, axis=1, keepdims=True)

    model = build_model(args.model, device=args.device)
    q = model.encode(
        [c["question"] for c in cases], convert_to_numpy=True, batch_size=64
    ).astype(np.float32)
    q /= np.linalg.norm(q, axis=1, keepdims=True)

    for c in cases:
        sims = q[cases.index(c)] @ gallery.T
        topk = set(ids[i] for i in np.argpartition(-sims, args.k)[: args.k])
        answers = set(c["answer_entities"])
        c["_recall"] = len(answers & topk) / len(answers) if answers else 0.0
        c["_anchor_hit"] = float(c["anchor"] in topk)

    print(f"node retrieval, k={args.k}, {len(cases)} questions\n")
    print(f"{'type':12} {'n':>3} {'recall@k':>9} {'anchor@k':>9}")
    for t in ["phenotype", "gene", "treatment"]:
        group = [c for c in cases if c["type"] == t]
        r = np.mean([c["_recall"] for c in group])
        a = np.mean([c["_anchor_hit"] for c in group])
        print(f"{t:12} {len(group):>3} {r:>9.3f} {a:>9.3f}")
    r = np.mean([c["_recall"] for c in cases])
    a = np.mean([c["_anchor_hit"] for c in cases])
    print(f"{'overall':12} {len(cases):>3} {r:>9.3f} {a:>9.3f}")


if __name__ == "__main__":
    main()
