#!/usr/bin/env python3
"""Score the graph-edge crawler on the quality-in-context gold (build seq: crawler).

The traversal counterpart of eval_score.py, reporting the same two numbers over the
same 180-question gold so the crawler's column sits directly beside node-text and
triple-text retrieval:

  answer recall — of a disease's true neighbours (its phenotypes / genes / drugs),
                  how many did the crawl reach.
  anchor accuracy — did disambiguation pick the exact gold disease node. This is
                  stricter than the embedding evals' "anchor in top-k": the crawler
                  commits to one anchor, so it either walked from the right node or not.

Unlike the embedding evals there is no retrieval budget k of documents — traversal
returns every neighbour along the picked predicates — so recall is not capped by a
top-k. A near-ceiling recall here is expected *when anchoring and predicate-pick both
land*; this eval measures how often that front door holds, since the walk itself is
exact by construction (the gold answers are exactly those edges' endpoints).

    eval_crawl.py [--device cpu]
"""

import argparse
import json

import shape_common as sc
from crawl import Crawler

GOLD = sc.PROJECT_HOME / "eval" / "gold_monarch.jsonl"


def main():
    ap = argparse.ArgumentParser(description="Score the crawler against the gold.")
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()

    cases = [json.loads(x) for x in GOLD.read_text().splitlines() if x.strip()]
    crawler = Crawler(device=args.device)

    for case in cases:
        anchor_id, _preds, neighbours, _facts = crawler.crawl(case["question"])
        answers = set(case["answer_entities"])
        case["_recall"] = len(answers & neighbours) / len(answers) if answers else 0.0
        case["_anchor_hit"] = float(anchor_id == case["anchor"])

    def mean(vals):
        return sum(vals) / len(vals) if vals else 0.0

    print(f"crawler (graph-edge traversal), {len(cases)} questions\n")
    print(f"{'type':12} {'n':>3} {'recall':>9} {'anchor-acc':>11}")
    for t in ["phenotype", "gene", "treatment", "overall"]:
        group = cases if t == "overall" else [c for c in cases if c["type"] == t]
        print(
            f"{t:12} {len(group):>3} "
            f"{mean([c['_recall'] for c in group]):>9.3f} "
            f"{mean([c['_anchor_hit'] for c in group]):>11.3f}"
        )


if __name__ == "__main__":
    main()
