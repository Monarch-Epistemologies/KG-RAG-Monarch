#!/usr/bin/env python3
"""Pick which predicate(s) a question is asking about (build seq: crawler, step 2).

Ported from KG-RAG-EDS/bin/project_2_predicate_classifier.py. Embed each predicate's
description (config/crawler_predicates.yaml) and the question with the same model, rank
predicates by cosine to the question, and keep a set — not a single top pick, since a
question can span two relations (gene has two predicates, treatment has two).
No LLM in this path.

Two things did not port from v1 and were re-derived by calibration (--calibrate):
the MODEL is MiniLM, not the pipeline's SapBERT (SapBERT can't separate predicate
descriptions for sentence questions; see the config header), and SELECTION is a
relative margin (keep predicates within `margin` of the top score), not v1's absolute
0.30 cutoff, because the right set is "the top one plus anything nearly tied with it".

    classify_predicate.py "What are the symptoms of Marfan syndrome?"
    classify_predicate.py --calibrate      # score spread over eval/gold_monarch.jsonl
"""

import argparse
import json

import numpy as np
import yaml

import shape_common as sc
from embed_models import build_model

CONFIG = sc.PROJECT_HOME / "config" / "crawler_predicates.yaml"
GOLD = sc.PROJECT_HOME / "eval" / "gold_monarch.jsonl"
QCONFIG = sc.PROJECT_HOME / "config" / "eval_questions.yaml"


def load_config(path=CONFIG):
    """Return (embed_model, margin, predicates dict) from the YAML config."""
    with open(path) as fh:
        cfg = yaml.safe_load(fh)
    return cfg["embed_model"], cfg["margin"], cfg["predicates"]


def _unit(v):
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def classify(question, model, pred_ids, pred_emb):
    """Return [(predicate, score)] sorted by descending cosine similarity."""
    q = _unit(model.encode(question, convert_to_numpy=True).astype(np.float32))
    sims = pred_emb @ q
    return sorted(zip(pred_ids, sims.tolist()), key=lambda r: r[1], reverse=True)


def select_within_margin(ranked, margin):
    """From ranked [(id, score)] (descending), keep the top plus any within `margin`
    cosine of it. Pure selection rule, split out so it is testable without a model."""
    top = ranked[0][1]
    return [p for p, s in ranked if s >= top - margin]


def picked_predicates(question, model, pred_ids, pred_emb, margin):
    """The top predicate plus any within `margin` cosine of it, highest first."""
    return select_within_margin(classify(question, model, pred_ids, pred_emb), margin)


def _load_model_and_preds(device):
    embed_model, margin, predicates = load_config()
    model = build_model(embed_model, device=device)
    pred_ids = list(predicates)
    pred_emb = _unit(
        model.encode(list(predicates.values()), convert_to_numpy=True).astype(np.float32)
    )
    return model, margin, pred_ids, pred_emb


def calibrate(model, pred_ids, pred_emb, device):
    """Over the gold questions, report where each type's TRUE predicate lands versus
    the best distractor — the separation that tells us where to put the cutoff."""
    with open(QCONFIG) as fh:
        qcfg = yaml.safe_load(fh)
    truth = {t["name"]: set(t["predicates"]) for t in qcfg["types"]}
    cases = [json.loads(x) for x in GOLD.read_text().splitlines() if x.strip()]

    print(f"{'type':10} {'true-pred score':>16} {'best distractor':>16} {'margin':>8}")
    for t in truth:
        group = [c for c in cases if c["type"] == t]
        true_scores, distractor_scores = [], []
        for c in group:
            ranked = dict(classify(c["question"], model, pred_ids, pred_emb))
            true_scores.append(max(ranked[p] for p in truth[t]))
            distractor_scores.append(
                max(s for p, s in ranked.items() if p not in truth[t])
            )
        ts, ds = float(np.mean(true_scores)), float(np.mean(distractor_scores))
        print(f"{t:10} {ts:>16.3f} {ds:>16.3f} {ts - ds:>8.3f}")
    print(
        "\nA cutoff between the true-pred and distractor columns keeps the right "
        "predicate and drops the rest; a negative margin means SapBERT cannot tell "
        "them apart with these descriptions."
    )


def main():
    ap = argparse.ArgumentParser(description="Predicate classifier for the crawler.")
    ap.add_argument("question", nargs="*")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()

    model, margin, pred_ids, pred_emb = _load_model_and_preds(args.device)

    if args.calibrate:
        calibrate(model, pred_ids, pred_emb, args.device)
        return

    question = " ".join(args.question) or "What are the symptoms of Marfan syndrome?"
    picked = set(picked_predicates(question, model, pred_ids, pred_emb, margin))
    print(f"Q: {question}\n")
    for pred, score in classify(question, model, pred_ids, pred_emb):
        mark = "*" if pred in picked else " "
        print(f"  {mark} {score:.3f}  {pred}")
    print(f"\n(* = picked: within margin {margin} of the top score)")


if __name__ == "__main__":
    main()
