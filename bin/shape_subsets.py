#!/usr/bin/env python3
"""Size the candidate v2 subsets as triple corpora, and the phenotype frequencies.

Everything here is counted as induced edges — both endpoints inside the kept node
set — because that is what a triple corpus contains. Incident counts, which measure
how far a set reaches rather than what it holds, live in shape_per_disease.py.

Three measurements: the configured disease union at one and two hops, every disease
at one hop, and how many diseases each phenotype annotates.
"""

import shape_common as sc

TOP_PHENOTYPES = 15
TOP_CATEGORIES = 8
TOP_PREDICATES = 10
PHENOTYPE_PERCENTILES = [0.5, 0.75, 0.9, 0.99]

con = sc.connect()


def expand(source, target):
    """One hop out from `source`, writing the enlarged node set to `target`."""
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE {target} AS
        SELECT DISTINCT id FROM (
            SELECT subject AS id FROM edges
            WHERE subject IN (SELECT id FROM {source}) OR object IN (SELECT id FROM {source})
            UNION ALL
            SELECT object FROM edges
            WHERE subject IN (SELECT id FROM {source}) OR object IN (SELECT id FROM {source})
            UNION ALL
            SELECT id FROM {source}
        )
    """)


def induced(node_table):
    return con.execute(f"""
        SELECT count(*) FROM edges
        WHERE subject IN (SELECT id FROM {node_table})
          AND object IN (SELECT id FROM {node_table})
    """).fetchone()[0]


def size(node_table):
    return con.execute(f"SELECT count(*) FROM {node_table}").fetchone()[0]


cfg = sc.config()
con.execute("CREATE OR REPLACE TEMP TABLE pats (p VARCHAR)")
con.executemany("INSERT INTO pats VALUES (?)", [[p] for p in cfg["diseases"]])
con.execute(
    """
    CREATE OR REPLACE TEMP TABLE union_seeds AS
    SELECT DISTINCT n.id FROM nodes n
    JOIN pats ON lower(n.name) LIKE '%' || pats.p || '%'
    WHERE n.id LIKE ? || '%' AND (n.deprecated IS NULL OR n.deprecated = '')
""",
    [sc.SEED_PREFIX],
)
con.execute(
    """
    CREATE OR REPLACE TEMP TABLE all_diseases AS
    SELECT id FROM nodes
    WHERE id LIKE ? || '%' AND (deprecated IS NULL OR deprecated = '')
""",
    [sc.SEED_PREFIX],
)

expand("union_seeds", "union_h1")
expand("union_h1", "union_h2")
expand("all_diseases", "all_h1")

print(f"{'candidate subset':44} {'nodes':>9} {'induced triples':>16}")
for label, table in [
    (f"union of {len(cfg['diseases'])} diseases, one hop", "union_h1"),
    (f"union of {len(cfg['diseases'])} diseases, two hops", "union_h2"),
    (f"all {size('all_diseases'):,} diseases, one hop", "all_h1"),
]:
    print(f"{label:44} {size(table):>9,} {induced(table):>16,}")

print("\nnode categories in the all-diseases one-hop subset:")
for category, count in con.execute(
    """
    SELECT replace(coalesce(n.category, '?'), 'biolink:', ''), count(*) AS c
    FROM all_h1 h JOIN nodes n ON n.id = h.id
    GROUP BY 1 ORDER BY c DESC LIMIT ?
""",
    [TOP_CATEGORIES],
).fetchall():
    print(f"  {count:>9,}  {category}")

print("\npredicates within it:")
for predicate, count in con.execute(
    """
    SELECT replace(predicate, 'biolink:', ''), count(*) AS c FROM edges
    WHERE subject IN (SELECT id FROM all_h1) AND object IN (SELECT id FROM all_h1)
    GROUP BY 1 ORDER BY c DESC LIMIT ?
""",
    [TOP_PREDICATES],
).fetchall():
    print(f"  {count:>9,}  {predicate}")

# How discriminative is a phenotype? A term annotating a large share of all diseases
# carries little signal, and dense retrieval has no inverse-document-frequency
# mechanism to discount it the way a sparse retriever would.
con.execute("""
    CREATE OR REPLACE TEMP TABLE phenotype_use AS
    SELECT e.object AS phenotype, count(DISTINCT e.subject) AS n_diseases
    FROM edges e JOIN all_diseases d ON d.id = e.subject
    WHERE e.predicate = 'biolink:has_phenotype'
    GROUP BY e.object
""")
total_diseases = size("all_diseases")
print(
    f"\n{size('phenotype_use'):,} distinct phenotypes used across "
    f"{total_diseases:,} diseases"
)
for p in PHENOTYPE_PERCENTILES:
    value = con.execute(
        "SELECT quantile_cont(n_diseases, ?) FROM phenotype_use", [p]
    ).fetchone()[0]
    print(f"  p{p * 100:g}: annotates {value:,.0f} diseases")

print(f"\nthe {TOP_PHENOTYPES} most common phenotypes:")
for phenotype, name, n in con.execute(
    """
    SELECT u.phenotype, n.name, u.n_diseases
    FROM phenotype_use u JOIN nodes n ON n.id = u.phenotype
    ORDER BY u.n_diseases DESC LIMIT ?
""",
    [TOP_PHENOTYPES],
).fetchall():
    print(f"  {n:>6,}  {100 * n / total_diseases:>5.1f}%  {phenotype:<14} {name}")
