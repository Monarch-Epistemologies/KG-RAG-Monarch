#!/usr/bin/env python3
"""Score retrieval quality-in-context against the derived gold (build seq #3, eval).

For each gold question, embed it with the corpus's model, take the top-k nearest
documents, and measure recall of the answer entities — the graph neighbours a real
answer needs — plus anchor recall (did it at least surface the disease named).

Two corpora, same retrieval budget of k documents:
  node   — a document is a node; an answer is surfaced if that node is in the top-k.
  triple — a document is a triple; an answer is surfaced if it is an endpoint of a
           top-k triple, so the fact "X has_phenotype Y" can carry the answer directly.

These are traversal-shaped questions, so node-text retrieval is expected to score low
(it ranks text-similar nodes, not graph neighbours) and triple-text high (the fact is
itself a retrievable document). The gap is the nodes-vs-triples evidence.

The two corpora use different retrieval backends by necessity: the node vectors (~300k)
fit in memory, so cosine is one numpy matrix product; the triple vectors (~4M x 768,
~12 GB) do not, so cosine runs as a single streaming pass over the table, scoring every
question against each batch (one scan, not one scan per question).

    eval_score.py [--corpus node|triple] [-k 20] [--model ...]
"""

import argparse
import heapq
import json

import duckdb
import numpy as np

import shape_common as sc
from embed_models import build_model

DEFAULT_MODEL = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"
GOLD = sc.PROJECT_HOME / "eval" / "gold_monarch.jsonl"
DB = sc.PROJECT_HOME / "data" / "embeddings.duckdb"


def surfaced_node(con, qvecs, k, dim):
    """Node corpus: load all vectors once, cosine as a matrix product (fast, ~300k)."""
    ids, vecs = [], []
    for node_id, emb in con.execute(
        "SELECT id, embedding FROM node_vectors"
    ).fetchall():
        ids.append(node_id)
        vecs.append(emb)
    gallery = np.asarray(vecs, dtype=np.float32)
    gallery /= np.linalg.norm(gallery, axis=1, keepdims=True)
    q = qvecs / np.linalg.norm(qvecs, axis=1, keepdims=True)
    out = []
    for i in range(len(q)):
        sims = q[i] @ gallery.T
        out.append({ids[j] for j in np.argpartition(-sims, k)[:k]})
    return out


def surfaced_triple(con, qvecs, k, dim):
    """Triple corpus: too large to hold in memory, and one ORDER BY scan per question
    would re-read the ~12 GB table 180 times. Instead stream the table once and score
    every question against each batch, keeping a running top-k per question. A retrieved
    triple surfaces both of its endpoints."""
    q = qvecs / np.linalg.norm(qvecs, axis=1, keepdims=True)
    tops = [
        [] for _ in range(len(q))
    ]  # per question: min-heap of (sim, tie, (subj,obj))
    tie = 0
    cur = con.execute("SELECT subject, object, embedding FROM triple_vectors")
    while batch := cur.fetchmany(50_000):
        subs = [r[0] for r in batch]
        objs = [r[1] for r in batch]
        mat = np.asarray([r[2] for r in batch], dtype=np.float32)
        mat /= np.linalg.norm(mat, axis=1, keepdims=True)
        sims = q @ mat.T  # (n_questions, batch)
        for i in range(len(q)):
            row = sims[i]
            for j in np.argpartition(-row, k)[:k]:
                item = (float(row[j]), tie, (subs[j], objs[j]))
                tie += 1
                if len(tops[i]) < k:
                    heapq.heappush(tops[i], item)
                elif item[0] > tops[i][0][0]:
                    heapq.heapreplace(tops[i], item)
    return [{v for _, _, pair in heap for v in pair} for heap in tops]


BACKENDS = {"node": surfaced_node, "triple": surfaced_triple}


def main():
    ap = argparse.ArgumentParser(description="Score retrieval against the gold.")
    ap.add_argument("--corpus", choices=list(BACKENDS), default="node")
    ap.add_argument("-k", type=int, default=20)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()

    cases = [json.loads(line) for line in GOLD.read_text().splitlines() if line.strip()]

    model = build_model(args.model, device=args.device)
    dim = model.get_sentence_embedding_dimension()
    qvecs = model.encode(
        [c["question"] for c in cases], convert_to_numpy=True, batch_size=64
    ).astype(np.float32)

    con = duckdb.connect(str(DB), read_only=True)
    surfaced = BACKENDS[args.corpus](con, qvecs, args.k, dim)

    for case, hits in zip(cases, surfaced):
        answers = set(case["answer_entities"])
        case["_recall"] = len(answers & hits) / len(answers) if answers else 0.0
        case["_anchor_hit"] = float(case["anchor"] in hits)

    def mean(vals):
        return sum(vals) / len(vals) if vals else 0.0

    print(f"{args.corpus} retrieval, k={args.k}, {len(cases)} questions\n")
    print(f"{'type':12} {'n':>3} {'recall@k':>9} {'anchor@k':>9}")
    for t in ["phenotype", "gene", "treatment", "overall"]:
        group = cases if t == "overall" else [c for c in cases if c["type"] == t]
        print(
            f"{t:12} {len(group):>3} "
            f"{mean([c['_recall'] for c in group]):>9.3f} "
            f"{mean([c['_anchor_hit'] for c in group]):>9.3f}"
        )


if __name__ == "__main__":
    main()
