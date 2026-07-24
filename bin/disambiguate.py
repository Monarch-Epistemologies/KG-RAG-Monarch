#!/usr/bin/env python3
"""Disambiguate the anchor using the picked predicate(s) (build seq: crawler, step 3).

The glue between the two front-door steps. Anchor recall (anchor.py) returns the nodes
nearest the question by embedding; this step commits to one of them as the node to
traverse from.

v1 picked the candidate with the MOST edges of the picked predicate — the disease was
the unique hub in a single-disease graph, so counting swamped the leaf phenotypes. That
rule INVERTS at Monarch scale and was measured doing active harm (phenotype anchor
accuracy 0.05): with 29k diseases and dense shared predicates, a common phenotype node
is itself the object of hundreds of has_phenotype edges, so max-count picks "Celiac
disease" (an HP term, object of 290 edges) over the disease actually asked about. And it
was unnecessary — SapBERT, the far stronger entity-linker that v1 lacked, already ranks
the right disease first in most cases; max-count then throws that correct anchor away.

So v2 trusts the anchor and constrains it minimally: walk the candidates in embedding
rank order and take the FIRST that is a disease (anchor_category) AND carries at least
one edge of a picked predicate. The category test drops phenotype/gene mis-hits; the
has-edge test breaks the near-synonym tie the embedding cannot (e.g. the real cystic
fibrosis over "cystic fibrosis, non-human animal", which has no human phenotype edges).
No max-count. Measured lift: overall answer recall ~0.37 -> ~0.78. See eval_crawl.py.

Ported from KG-RAG-EDS/bin/project_2_disambiguate.py. The v2 reality it exposes: two
steps, two models, two databases. Candidates come from SapBERT vectors in
embeddings.duckdb (anchor.py); predicates from MiniLM (classify_predicate.py); the edge
existence check runs over the indexed graph.duckdb.

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


# The disease-anchored use cases resolve to MONDO nodes; the anchor must be one.
ANCHOR_PREFIX = "MONDO:"


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


def disambiguate(gcon, candidates, predicates, anchor_prefix=ANCHOR_PREFIX):
    """Take the first candidate, in embedding-rank order, that is an anchor-namespace
    node AND carries at least one edge of a picked predicate.

    Category drops phenotype/gene mis-hits; the has-edge test breaks the near-synonym
    tie the embedding cannot. Fall back to the top anchor-namespace candidate (predicate
    pick may have missed), then to the top candidate overall.
    Returns (rank, (id, category, text, sim), count) or (None, None, 0) if no candidates.
    """
    if not candidates:
        return (None, None, 0)
    first_in_ns = None
    for rank, cand in enumerate(candidates):
        if not cand[0].startswith(anchor_prefix):
            continue
        if first_in_ns is None:
            first_in_ns = (rank, cand)
        count = edge_count_of(gcon, cand[0], predicates)
        if count >= 1:
            return (rank, cand, count)
    rank, cand = first_in_ns if first_in_ns else (0, candidates[0])
    return (rank, cand, edge_count_of(gcon, cand[0], predicates))


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
