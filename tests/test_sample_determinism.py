"""Error class 1: an unfair sample would invalidate the model comparison.

The synonym eval scores every model on a seeded sample of gallery names and synonym
queries, and the whole comparison is only valid if that sample is byte-identical across
runs — otherwise each model was scored on different data. This checks the property the
eval relies on: DuckDB's seeded reservoir sample is deterministic across fresh
connections. If this fails, the reported MRR table is not comparable and the eval's
sampling must be made deterministic before the numbers can be trusted.
"""

import duckdb
from conftest import DATA, require

SEED = 7
GALLERY_N = 5_000
QUERY_N = 5_000


def _sample():
    con = duckdb.connect()
    con.execute(
        f"""CREATE TABLE nodes AS
            SELECT id, name, synonym
            FROM read_csv('{DATA / "nodes.tsv"}', delim='\t', header=true)
            WHERE name IS NOT NULL AND name <> ''"""
    )
    gallery = [
        r[0]
        for r in con.execute(
            f"SELECT id FROM nodes USING SAMPLE {GALLERY_N} ROWS (reservoir, {SEED})"
        ).fetchall()
    ]
    queries = [
        r[0]
        for r in con.execute(
            f"""SELECT id FROM nodes WHERE synonym IS NOT NULL AND synonym <> ''
                USING SAMPLE {QUERY_N} ROWS (reservoir, {SEED})"""
        ).fetchall()
    ]
    con.close()
    return gallery, queries


def test_SeededReservoirSample_WHEN_same_seed_across_connections_SHOULD_be_identical():
    require(DATA / "nodes.tsv")
    gallery_a, queries_a = _sample()
    gallery_b, queries_b = _sample()
    assert gallery_a == gallery_b, (
        "gallery sample differs across connections; eval unfair"
    )
    assert queries_a == queries_b, (
        "query sample differs across connections; eval unfair"
    )
    # Non-degenerate: a proper subset, not the whole table (which would be trivially
    # identical). The query count runs below QUERY_N because DuckDB applies the sample
    # before the synonym filter — fine, as long as it is stable, which the asserts
    # above establish.
    assert 0 < len(queries_a) < GALLERY_N
    assert len(gallery_a) == GALLERY_N
