#!/usr/bin/env python3
"""Build the quality-in-context gold from the graph (build seq #3, eval).

For each question type in config/eval_questions.yaml, sample diseases that carry the
type's predicate(s), template a question, and derive the answer set from the graph
(all neighbours reached by those predicates in the right direction and namespace). No
answer is hand-labeled; the graph is the answer key, so re-running regenerates it.

These are traversal-shaped questions — the answer is a disease's graph neighbours, not
a text-similar node — which is exactly the point: they measure whether a retrieval
method can surface the *facts* a real question needs, and they are where node-text and
triple-text retrieval are expected to diverge. Writes eval/gold_monarch.jsonl.
"""

import json

import duckdb

import shape_common as sc

CONFIG = sc.PROJECT_HOME / "config" / "eval_questions.yaml"
NODES = sc.PROJECT_HOME / "data" / "nodes.tsv"
EDGES = sc.PROJECT_HOME / "data" / "edges.tsv"
OUT = sc.PROJECT_HOME / "eval" / "gold_monarch.jsonl"
# all_varchar so the `deprecated` column stays text ('' / 'True') rather than being
# auto-typed BOOL, which chokes on the empty string.
READ = "delim='\t', header=true, all_varchar=true"

with open(CONFIG) as fh:
    import yaml

    cfg = yaml.safe_load(fh)

con = duckdb.connect()
con.execute(f"CREATE VIEW nodes AS SELECT * FROM read_csv('{NODES}', {READ})")
con.execute(f"CREATE VIEW edges AS SELECT * FROM read_csv('{EDGES}', {READ})")

cases = []
for t in cfg["types"]:
    preds = "(" + ",".join(f"'{p}'" for p in t["predicates"]) + ")"
    # `disease` is the anchor MONDO node; `answer` is the neighbour, on the side of
    # the edge set by direction, restricted to the answer namespace.
    if t["direction"] == "out":
        disease_col, answer_col = "subject", "object"
    else:
        disease_col, answer_col = "object", "subject"

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE pairs AS
        SELECT e.{disease_col} AS disease, e.{answer_col} AS answer
        FROM edges e
        WHERE e.predicate IN {preds}
          AND e.{disease_col} LIKE 'MONDO:%'
          AND e.{answer_col} LIKE '{t["answer_ns"]}:%'
    """)
    # Anchor must be a named, non-deprecated disease; keep those with enough answers
    # to make the question meaningful, then take a deterministic pseudo-random sample.
    # (USING SAMPLE would push down below the GROUP BY and sample raw pairs, so the
    # HAVING count never survives; ORDER BY hash(id) LIMIT samples the grouped result.)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE anchors AS
        SELECT id, name, n_answers FROM (
            SELECT p.disease AS id, n.name, count(DISTINCT p.answer) AS n_answers
            FROM pairs p JOIN nodes n ON n.id = p.disease
            WHERE n.name IS NOT NULL AND n.name <> ''
              AND (n.deprecated IS NULL OR n.deprecated = '')
            GROUP BY p.disease, n.name
            HAVING count(DISTINCT p.answer) >= {t["min_answers"]}
        )
        ORDER BY hash(id || '{cfg["seed"]}') LIMIT {cfg["per_type"]}
    """)

    for anchor_id, name, _ in con.execute(
        "SELECT id, name, n_answers FROM anchors"
    ).fetchall():
        answers = [
            r[0]
            for r in con.execute(
                "SELECT DISTINCT answer FROM pairs WHERE disease = ?", [anchor_id]
            ).fetchall()
        ]
        cases.append(
            {
                "id": f"{t['name']}-{anchor_id}",
                "type": t["name"],
                "question": t["template"].format(disease=name),
                "anchor": anchor_id,
                "answer_entities": answers,
            }
        )

OUT.parent.mkdir(parents=True, exist_ok=True)
with open(OUT, "w") as fh:
    for case in cases:
        fh.write(json.dumps(case) + "\n")

print(f"{len(cases)} cases -> {OUT.relative_to(sc.PROJECT_HOME)}")
for t in cfg["types"]:
    n = sum(1 for c in cases if c["type"] == t["name"])
    sizes = [len(c["answer_entities"]) for c in cases if c["type"] == t["name"]]
    med = sorted(sizes)[len(sizes) // 2] if sizes else 0
    print(f"  {t['name']:10} {n:>3} cases, median {med} answers")
