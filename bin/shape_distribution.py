#!/usr/bin/env python3
"""Subgraph-size distribution over every MONDO disease term in the dump.

One seed per disease — no name matching — so these numbers are a different unit
from shape_per_disease.py, which seeds from a name-matched family of subtypes.

h1 is exact. h2 edges are an upper bound: the sum of frontier-node degrees, which
double-counts any edge with both ends in the frontier. A random sample is also
counted exactly so the size of that error is known rather than assumed.
"""

import shape_common as sc

PERCENTILES = [0.5, 0.75, 0.9, 0.95, 0.99, 0.999]
BUDGET_THRESHOLDS = [100_000, 500_000, 1_000_000, 2_000_000]
SAMPLE_SIZE = 12
SAMPLE_SEED = 42

con = sc.connect()
sc.add_degree_table(con)

con.execute(
    """
    CREATE OR REPLACE TEMP TABLE diseases AS
    SELECT id FROM nodes
    WHERE id LIKE ? || '%' AND (deprecated IS NULL OR deprecated = '')
""",
    [sc.SEED_PREFIX],
)

# One row per (disease, neighbour) pair, following edges in both directions.
con.execute("""
    CREATE OR REPLACE TEMP TABLE nbr AS
    SELECT DISTINCT d.id AS disease, e.other
    FROM diseases d
    JOIN (
        SELECT subject AS id, object AS other FROM edges
        UNION ALL
        SELECT object AS id, subject AS other FROM edges
    ) e ON e.id = d.id
""")
con.execute("""
    CREATE OR REPLACE TEMP TABLE shape AS
    SELECT n.disease, count(*) AS h1_nodes, sum(g.deg) AS h2_edges_ub
    FROM nbr n JOIN degree g ON g.id = n.other
    GROUP BY n.disease
""")

total = con.execute("SELECT count(*) FROM shape").fetchone()[0]
print(f"{total:,} MONDO terms with at least one edge\n")
print(f"{'':6} {'h1 nodes':>12} {'h2 edges (upper bd)':>22}")
for p in PERCENTILES:
    h1, h2 = con.execute(
        "SELECT quantile_cont(h1_nodes, ?), quantile_cont(h2_edges_ub, ?) FROM shape",
        [p, p],
    ).fetchone()
    print(f"{'p' + f'{p * 100:g}':6} {h1:>12,.0f} {h2:>22,.0f}")
h1, h2 = con.execute("SELECT max(h1_nodes), max(h2_edges_ub) FROM shape").fetchone()
print(f"{'max':6} {h1:>12,.0f} {h2:>22,.0f}")

print("\ndiseases exceeding a two-hop triple budget (upper bound):")
for threshold in BUDGET_THRESHOLDS:
    over = con.execute(
        "SELECT count(*) FROM shape WHERE h2_edges_ub > ?", [threshold]
    ).fetchone()[0]
    print(f"  > {threshold:>9,}: {over:>6,}  ({100 * over / total:.1f}%)")

print(f"\nexact h2 for a random sample of {SAMPLE_SIZE}, against the upper bound:")
print(
    f"  {'disease':16} {'h1 edges':>9} {'h2 edges':>10} {'upper bd':>10} {'ratio':>6}"
)
sample = con.execute(
    f"SELECT disease FROM shape USING SAMPLE {SAMPLE_SIZE} ROWS (reservoir, {SAMPLE_SEED})"
).fetchall()
for (disease,) in sample:
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE frontier AS
        SELECT DISTINCT other AS id FROM (
            SELECT object AS other FROM edges WHERE subject = ?
            UNION ALL SELECT subject FROM edges WHERE object = ?)
    """,
        [disease, disease],
    )
    h1_edges = con.execute(
        "SELECT count(*) FROM edges WHERE subject = ? OR object = ?", [disease, disease]
    ).fetchone()[0]
    h2_edges = con.execute("""
        SELECT count(*) FROM edges
        WHERE subject IN (SELECT id FROM frontier) OR object IN (SELECT id FROM frontier)
    """).fetchone()[0]
    upper = con.execute(
        "SELECT h2_edges_ub FROM shape WHERE disease = ?", [disease]
    ).fetchone()[0]
    print(
        f"  {disease:16} {h1_edges:>9,} {h2_edges:>10,} {upper:>10,} "
        f"{upper / max(h2_edges, 1):>6.2f}"
    )
