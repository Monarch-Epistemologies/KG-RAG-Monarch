"""Error class 1: an unfair sample would invalidate the model comparison.

The synonym eval scores every model on a seeded sample of gallery names and synonym
queries, and the whole comparison is only valid if that sample is byte-identical across
runs — otherwise each model was scored on different data. This checks the property the
eval relies on, using the eval's ACTUAL sampling: a deterministic ORDER BY hash(id ||
SEED) LIMIT n (bin/eval_synonym_retrieval.py).

It replaces an earlier check of DuckDB's `USING SAMPLE (reservoir, seed)`, which the eval
used until issue #1: the parallel reservoir sample is not byte-identical across
connections under multithreading, so that test failed intermittently under full-suite CPU
load and the eval's sample was not reproducibly fair. hash-ordering is stable regardless
of thread count. To pin that regression this test also samples at the default thread count
AND at threads=1 and asserts all four agree.
"""

import duckdb
from conftest import DATA, require

SEED = 7
GALLERY_N = 5_000
QUERY_N = 5_000


def _sample(threads=None):
    con = duckdb.connect()
    if threads:
        con.execute(f"SET threads={threads}")
    con.execute(
        f"""CREATE TABLE nodes AS
            SELECT id, name, synonym
            FROM read_csv('{DATA / "nodes.tsv"}', delim='\t', header=true)
            WHERE name IS NOT NULL AND name <> ''"""
    )
    gallery = [
        r[0]
        for r in con.execute(
            f"SELECT id FROM nodes ORDER BY hash(id || '{SEED}') LIMIT {GALLERY_N}"
        ).fetchall()
    ]
    queries = [
        r[0]
        for r in con.execute(
            f"""SELECT id FROM nodes WHERE synonym IS NOT NULL AND synonym <> ''
                ORDER BY hash(id || '{SEED}') LIMIT {QUERY_N}"""
        ).fetchall()
    ]
    con.close()
    return gallery, queries


def test_SeededHashSample_WHEN_same_seed_across_connections_SHOULD_be_identical():
    require(DATA / "nodes.tsv")
    gallery_a, queries_a = _sample()
    gallery_b, queries_b = _sample()
    assert gallery_a == gallery_b, (
        "gallery sample differs across connections; eval unfair"
    )
    assert queries_a == queries_b, (
        "query sample differs across connections; eval unfair"
    )
    assert len(gallery_a) == GALLERY_N
    assert len(queries_a) == QUERY_N  # deterministic count, unlike reservoir + filter


def test_SeededHashSample_WHEN_thread_count_varies_SHOULD_be_identical():
    """The regression from issue #1: reservoir sampling differed by thread scheduling.
    hash-ordering must not — assert default-threaded and single-threaded samples agree."""
    require(DATA / "nodes.tsv")
    default_gallery, default_queries = _sample()
    single_gallery, single_queries = _sample(threads=1)
    assert default_gallery == single_gallery
    assert default_queries == single_queries
