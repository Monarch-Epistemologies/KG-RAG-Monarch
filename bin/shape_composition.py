#!/usr/bin/env python3
"""What the whole graph is made of, along the axes a pare-back would argue over.

Closure from any disease is effectively the whole graph, so paring back cannot be
done by distance — it has to be done by relevance. This reports the levers that
exist: species, node category, predicate, evidence level and knowledge source, each
with the share of nodes or edges it controls.
"""

import shape_common as sc

TOP = 15

con = sc.connect()

total_nodes, total_edges = con.execute(
    "SELECT (SELECT count(*) FROM nodes), (SELECT count(*) FROM edges)"
).fetchone()
print(f"{total_nodes:,} nodes, {total_edges:,} edges\n")


def breakdown(title, table, expression, total, where=""):
    print(f"{title}:")
    rows = con.execute(f"""
        SELECT coalesce({expression}, '(none)') AS bucket, count(*) AS c
        FROM {table} {where}
        GROUP BY 1 ORDER BY c DESC LIMIT {TOP}
    """).fetchall()
    for bucket, count in rows:
        print(f"  {count:>10,} {100 * count / total:>6.1f}%  {bucket}")
    shown = sum(c for _, c in rows)
    if shown < total:
        print(f"  {total - shown:>10,} {100 * (total - shown) / total:>6.1f}%  (rest)")
    print()


breakdown(
    "nodes by category", "nodes", "replace(category, 'biolink:', '')", total_nodes
)
breakdown("nodes by species", "nodes", "in_taxon_label", total_nodes)
breakdown(
    "edges by predicate", "edges", "replace(predicate, 'biolink:', '')", total_edges
)
breakdown("edges by knowledge level", "edges", "knowledge_level", total_edges)
breakdown("edges by agent type", "edges", "agent_type", total_edges)
breakdown(
    "edges by primary knowledge source",
    "edges",
    "primary_knowledge_source",
    total_edges,
)

# Species has to be judged on edges, not nodes: a taxon-less node such as a MONDO
# disease or an HP phenotype is species-neutral, but the edge attaching it to a
# zebrafish gene is not.
print("edges by species of their endpoints:")
for bucket, count in con.execute("""
    WITH tagged AS (
        SELECT CASE
            WHEN s.in_taxon_label IS NULL AND o.in_taxon_label IS NULL THEN 'both taxon-free'
            WHEN coalesce(s.in_taxon_label, 'Homo sapiens') = 'Homo sapiens'
             AND coalesce(o.in_taxon_label, 'Homo sapiens') = 'Homo sapiens' THEN 'human (or taxon-free)'
            ELSE 'touches a non-human species'
        END AS bucket
        FROM edges e
        JOIN nodes s ON s.id = e.subject
        JOIN nodes o ON o.id = e.object
    )
    SELECT bucket, count(*) AS c FROM tagged GROUP BY 1 ORDER BY c DESC
""").fetchall():
    print(f"  {count:>10,} {100 * count / total_edges:>6.1f}%  {bucket}")
