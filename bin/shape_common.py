#!/usr/bin/env python3
"""Shared paths and helpers for the subgraph-shape measurements (doc section 1).

The dump itself is not duplicated into this repo: v2 reads the KGX files that v1
already pulled and pinned. That makes KG-RAG-EDS a data dependency of these
scripts, which is deliberate while the two repos sit side by side.
"""

import pathlib

import duckdb
import yaml

PROJECT_HOME = pathlib.Path(__file__).resolve().parents[1]
EDS_HOME = PROJECT_HOME.parent / "KG-RAG-EDS"
NODES_TSV = EDS_HOME / "data" / "monarch-kg_nodes.tsv"
EDGES_TSV = EDS_HOME / "data" / "monarch-kg_edges.tsv"
DB = PROJECT_HOME / "data" / "kg_shape.duckdb"
CONFIG = PROJECT_HOME / "config" / "shape_probe.yaml"

# The raw dump is unquoted TSV with free text in description and synonym fields,
# so DuckDB's default quote handling has to be switched off.
READ_OPTS = "delim='\t', quote='', all_varchar=true, header=true"

# Disease seeds are MONDO terms only, excluding those the ontology has retired.
SEED_PREFIX = "MONDO:"


def config():
    """Load the hand-tuned probe inputs."""
    with open(CONFIG) as fh:
        return yaml.safe_load(fh)


def connect(read_only=True):
    if not DB.exists():
        raise SystemExit(f"{DB} not found — run bin/shape_load.py first")
    return duckdb.connect(str(DB), read_only=read_only)


def add_degree_table(con):
    """Undirected degree for every node, computed once per connection."""
    con.execute("""
        CREATE OR REPLACE TEMP TABLE degree AS
        SELECT id, count(*) AS deg
        FROM (SELECT subject AS id FROM edges UNION ALL SELECT object FROM edges)
        GROUP BY id
    """)
