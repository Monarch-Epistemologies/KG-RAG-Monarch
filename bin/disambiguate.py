#!/usr/bin/env python3
"""Disambiguate the anchor using the picked predicate(s) (build seq: crawler, step 3).

The glue between the two front-door steps. Anchor recall (anchor.py) returns the nodes
nearest the question by embedding, but nearest-by-meaning is often a symptom or a gene,
not the disease we want to traverse from. The fix is graph-native and deliberately
simple: among the candidates, pick the one with the MOST edges of the picked
predicate(s) — the disease is a hub (a disease has hundreds of has_phenotype edges)
while a leaf phenotype has a handful, so counting swamps the leaves. The predicate set
constrains the anchor.

Ported from KG-RAG-EDS/bin/project_2_disambiguate.py. The v2 reality this exposes: the
two steps use two models in two databases. Candidates come from SapBERT vectors in
embeddings.duckdb (anchor.py); predicates come from MiniLM (classify_predicate.py); the
edge counts run over the indexed graph.duckdb. Three moving parts, one anchor.

It is a heuristic: it assumes the anchor is well-connected, and the right disease still
has to be IN the candidate pool — a recall miss defeats any method — so anchor runs
with a generous k.

Run with a question as args, or no args for the test set.
"""

import sys

import duckdb

import shape_common as sc
from anchor import anchor
from anchor import DB as EMB_DB
from anchor import K as RECALL_K
from anchor import MODEL as ANCHOR_MODEL
from classify_predicate import _load_model_and_preds, picked_predicates
from embed_models import build_model

GRAPH_DB = sc.PROJECT_HOME / "data" / "graph.duckdb"

TEST_QUESTIONS = [
    "What gene is associated with Marfan syndrome?",
    "What are the symptoms of cystic fibrosis?",
    "What is used to treat Marfan syndrome?",
]


def edge_count_of(gcon, node_id, predicates):
    """How many edges have node_id on either side with one of these predicates."""
    return gcon.execute(
        """
        SELECT count(*) FROM edges
        WHERE list_contains($preds, predicate)
          AND (subject = $n OR object = $n)
        """,
        {"preds": list(predicates), "n": node_id},
    ).fetchone()[0]


def disambiguate(gcon, candidates, predicates):
    """Pick the candidate most connected via the picked predicates (the hub).

    Ties break toward the better embedding rank (strict >, first wins).
    Returns (rank, (id, category, text, sim), count) or (None, None, 0).
    """
    best = (None, None, 0)
    for rank, cand in enumerate(candidates):
        count = edge_count_of(gcon, cand[0], predicates)
        if count > best[2]:
            best = (rank, cand, count)
    return best


def main():
    econ = duckdb.connect(str(EMB_DB), read_only=True)
    gcon = duckdb.connect(str(GRAPH_DB), read_only=True)
    anchor_model = build_model(ANCHOR_MODEL, device="cpu")
    pred_model, margin, pred_ids, pred_emb = _load_model_and_preds("cpu")

    questions = [" ".join(sys.argv[1:])] if len(sys.argv) > 1 else TEST_QUESTIONS
    for question in questions:
        preds = picked_predicates(question, pred_model, pred_ids, pred_emb, margin)
        candidates = anchor(econ, anchor_model, question, k=RECALL_K)
        rank, chosen, count = disambiguate(gcon, candidates, preds)

        print(f"\nQ: {question}")
        print(f"   predicates: {[p.replace('biolink:', '') for p in preds]}")
        top = candidates[0]
        tcat = (top[1] or "").replace("biolink:", "")
        print(f"   top embedding hit: {tcat} {top[0]} {top[2][:40]}")
        if chosen is None:
            print("   -> no candidate has an edge of these predicates (no usable anchor)")
        else:
            ccat = (chosen[1] or "").replace("biolink:", "")
            print(
                f"   -> anchor: {ccat} {chosen[0]} {chosen[2][:40]} "
                f"(rank {rank} of {RECALL_K}, {count} edges)"
            )


if __name__ == "__main__":
    main()
