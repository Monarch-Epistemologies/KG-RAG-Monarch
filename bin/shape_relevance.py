#!/usr/bin/env python3
"""Pare the graph back by relevance rather than by distance or by what fits.

Closure from any disease is effectively the whole graph, so a hop radius cannot
define the corpus and capacity should not. This applies the cuts in
config/shape_probe.yaml cumulatively, each one arguable from v2's use cases, and
reports what survives at every step: nodes, induced triples, and how many diseases
still have at least one edge — the coverage the cut costs.
"""

import shape_common as sc

con = sc.connect()

total_diseases = con.execute(
    "SELECT count(*) FROM nodes WHERE id LIKE ? || '%' AND (deprecated IS NULL OR deprecated = '')",
    [sc.SEED_PREFIX],
).fetchone()[0]

print(f"{'relevance cut':48} {'nodes':>10} {'triples':>12} {'diseases kept':>14}")

for cut in sc.config()["relevance_cuts"]:
    conditions = []
    if cut.get("drop_nonhuman"):
        # A taxon-free node (a MONDO disease, an HP phenotype) is species-neutral;
        # what disqualifies an edge is an endpoint belonging to another species.
        conditions.append("""
            coalesce(s.in_taxon_label, 'Homo sapiens') = 'Homo sapiens'
            AND coalesce(o.in_taxon_label, 'Homo sapiens') = 'Homo sapiens'
        """)
    for predicate in cut.get("drop_predicates") or []:
        conditions.append(f"e.predicate <> '{predicate}'")
    for category in cut.get("drop_categories") or []:
        conditions.append(f"coalesce(s.category, '') <> '{category}'")
        conditions.append(f"coalesce(o.category, '') <> '{category}'")
    where = " AND ".join(conditions) if conditions else "true"

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE kept AS
        SELECT e.subject, e.object FROM edges e
        JOIN nodes s ON s.id = e.subject
        JOIN nodes o ON o.id = e.object
        WHERE {where}
    """)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE kept_nodes AS
        SELECT DISTINCT id FROM
        (SELECT subject AS id FROM kept UNION ALL SELECT object FROM kept)
    """)

    triples = con.execute("SELECT count(*) FROM kept").fetchone()[0]
    nodes = con.execute("SELECT count(*) FROM kept_nodes").fetchone()[0]
    diseases = con.execute(
        """
        SELECT count(*) FROM kept_nodes k JOIN nodes n ON n.id = k.id
        WHERE k.id LIKE ? || '%' AND (n.deprecated IS NULL OR n.deprecated = '')
    """,
        [sc.SEED_PREFIX],
    ).fetchone()[0]
    print(
        f"{cut['label']:48} {nodes:>10,} {triples:>12,} "
        f"{diseases:>9,} {100 * diseases / total_diseases:>4.0f}%"
    )
