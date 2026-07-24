#!/usr/bin/env python3
"""Graph-edge crawler: question -> anchor -> predicate -> neighbours (build seq: crawler).

Assembles the four steps into one retrieval path, the graph-native counterpart of
text-embedding retrieve.py. Ported from KG-RAG-EDS/bin/project_2_kg_rag_query.py, minus
generation — this returns the retrieved *facts*, the graph neighbours a real answer
needs; handing them to an LLM is a later, model-agnostic seam.

    question
      -> anchor        SapBERT nearest nodes           (embeddings.duckdb)
      -> predicate     MiniLM vs predicate descriptions (its own space)
      -> disambiguate  hub by picked-predicate edges    (graph.duckdb)
      -> traverse      one hop along each picked predicate (graph.duckdb)

Two embedding models by design (see config/crawler_predicates.yaml): SapBERT links the
entity, MiniLM classifies the relation. The crawl() function is what the gold scorer
(eval_crawl.py) calls per question; the CLI shows one question's trace.

    crawl.py "What gene is associated with Marfan syndrome?"
"""

import sys

import duckdb

from anchor import DB as EMB_DB
from anchor import K as RECALL_K
from anchor import MODEL as ANCHOR_MODEL
from anchor import anchor
from classify_predicate import _load_model_and_preds, picked_predicates
from disambiguate import GRAPH_DB, disambiguate
from embed_models import build_model
from traverse import traverse


class Crawler:
    """Holds the two models and two connections so a batch (the scorer) opens them once."""

    def __init__(self, device="cpu"):
        self.econ = duckdb.connect(str(EMB_DB), read_only=True)
        self.gcon = duckdb.connect(str(GRAPH_DB), read_only=True)
        self.anchor_model = build_model(ANCHOR_MODEL, device=device)
        self.pred_model, self.margin, self.pred_ids, self.pred_emb = (
            _load_model_and_preds(device)
        )

    def crawl(self, question, k=RECALL_K):
        """Return (anchor_id, predicates, neighbour_ids, facts).

        neighbour_ids is the set reached by traversing every picked predicate from the
        disambiguated anchor; facts keeps the (predicate, other_id, name, dir) detail.
        anchor_id is None when no candidate carries any picked-predicate edge.
        """
        preds = picked_predicates(
            question, self.pred_model, self.pred_ids, self.pred_emb, self.margin
        )
        candidates = anchor(self.econ, self.anchor_model, question, k=k)
        _rank, chosen, _count = disambiguate(self.gcon, candidates, preds)
        if chosen is None:
            return None, preds, set(), []

        anchor_id = chosen[0]
        neighbours, facts = set(), []
        for pred in preds:
            for other_id, category, name, direction in traverse(
                self.gcon, anchor_id, pred
            ):
                neighbours.add(other_id)
                facts.append((pred, other_id, name, direction))
        return anchor_id, preds, neighbours, facts


def main():
    question = " ".join(sys.argv[1:]) or "What gene is associated with Marfan syndrome?"
    crawler = Crawler()
    anchor_id, preds, neighbours, facts = crawler.crawl(question)

    print(f"Q: {question}\n")
    if anchor_id is None:
        print("No usable anchor (no candidate carries the picked predicates).")
        return
    print(f"Anchor:     {anchor_id}")
    print(f"Predicates: {[p.replace('biolink:', '') for p in preds]}")
    print(f"Facts:      {len(facts)} ({len(neighbours)} distinct neighbours)\n")
    for pred, other_id, name, direction in facts[:12]:
        p = pred.replace("biolink:", "")
        print(f"  [{direction}] {p:28} {other_id:16} {name or '(no name)'}")
    if len(facts) > 12:
        print(f"  ... and {len(facts) - 12} more")


if __name__ == "__main__":
    main()
