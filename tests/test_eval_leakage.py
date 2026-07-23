"""Error class 2: leakage would make the synonym eval too easy or unfairly hard.

Two failure modes on the generated query set (eval/synonym_queries.jsonl):

- Trivial leak: the query string equals its own target node's name. Then a hit needs
  no semantic ability at all — pure string identity. The eval builder is supposed to
  skip synonyms equal to the name, so this must be zero.
- Ambiguity: the query string equals some *other* node's name. Then that other node is
  a legitimate match the scorer counts as a miss, deflating every model's score. This
  is expected to be small and hits all models equally (so it does not flip the
  ranking), but a large rate would mean the absolute numbers are misleading.
"""

import json

import duckdb
from conftest import DATA, EVAL, require

MAX_AMBIGUOUS_RATE = 0.05


def _load():
    queries = [
        json.loads(line)
        for line in (EVAL / "synonym_queries.jsonl").read_text().splitlines()
        if line.strip()
    ]
    con = duckdb.connect()
    con.execute(
        f"""CREATE TABLE nodes AS
            SELECT id, lower(trim(name)) AS name
            FROM read_csv('{DATA / "nodes.tsv"}', delim='\t', header=true)
            WHERE name IS NOT NULL AND name <> ''"""
    )
    # name -> set of node ids that carry it (a name is not guaranteed unique)
    name_to_ids = {}
    for node_id, name in con.execute("SELECT id, name FROM nodes").fetchall():
        name_to_ids.setdefault(name, set()).add(node_id)
    con.close()
    return queries, name_to_ids


def test_SynonymQueries_WHEN_built_SHOULD_never_equal_target_name():
    require(EVAL / "synonym_queries.jsonl", DATA / "nodes.tsv")
    queries, name_to_ids = _load()
    trivial = [
        q
        for q in queries
        if q["target"] in name_to_ids.get(q["query"].strip().lower(), set())
    ]
    assert not trivial, (
        f"{len(trivial)} queries equal their own target's name (trivial hit); "
        f"the builder should skip synonyms equal to the name, e.g. {trivial[:3]}"
    )


def test_SynonymQueries_WHEN_query_matches_another_node_name_SHOULD_be_rare():
    require(EVAL / "synonym_queries.jsonl", DATA / "nodes.tsv")
    queries, name_to_ids = _load()
    ambiguous = [
        q
        for q in queries
        if name_to_ids.get(q["query"].strip().lower(), set()) - {q["target"]}
    ]
    rate = len(ambiguous) / len(queries)
    assert rate <= MAX_AMBIGUOUS_RATE, (
        f"{rate:.1%} of queries match another node's name (gold ambiguity), "
        f"above the {MAX_AMBIGUOUS_RATE:.0%} bar; absolute MRR is deflated"
    )
