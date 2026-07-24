"""Unit tests for the graph-edge crawler's logic (bin/{traverse,disambiguate,
classify_predicate}.py).

These are UNIT tests: they run against a hand-built tiny graph in an in-memory DuckDB,
with no embedding model and no access to the multi-GB stores. The parts that need a real
model and the real corpus (anchor.py, Crawler.crawl end to end) are integration, scored
by bin/eval_crawl.py, and deliberately not exercised here. What is unit-testable is the
graph logic — traversal direction, the disambiguation selection rule, edge counting — and
the pure margin rule, which is where the crawler's behaviour actually lives.

The fixture mirrors the real graph.duckdb schema: nodes(id, category, name),
edges(subject, object, predicate).
"""

import duckdb
import pytest

from classify_predicate import select_within_margin
from disambiguate import disambiguate, edge_count_of
from traverse import traverse

PHENO = "biolink:has_phenotype"
CAUSES = "biolink:causes"
SUBCLASS = "biolink:subclass_of"
TREATS = "biolink:treats"

DISEASE = "biolink:Disease"
FEATURE = "biolink:PhenotypicFeature"
GENE = "biolink:Gene"


@pytest.fixture
def graph():
    """A small graph exercising every traversal case:

    MONDO:1 (hub disease) --has_phenotype--> HP:1, HP:2, HP:9  (HP:9 absent from nodes)
    HGNC:1  --causes--> MONDO:1                                (anchor on the object side)
    MONDO:1 --subclass_of--> MONDO:2      and  MONDO:3 --subclass_of--> MONDO:1  (both dirs)
    MONDO:2 --has_phenotype--> HP:1                            (a second, smaller hub)
    MONDO:9 (near-synonym) and MONDO:8: diseases with NO has_phenotype edges.
    """
    con = duckdb.connect()
    con.execute("CREATE TABLE nodes (id VARCHAR, category VARCHAR, name VARCHAR)")
    con.execute("CREATE TABLE edges (subject VARCHAR, object VARCHAR, predicate VARCHAR)")
    nodes = [
        ("MONDO:1", DISEASE, "disease one"),
        ("MONDO:2", DISEASE, "disease two"),
        ("MONDO:3", DISEASE, "disease three"),
        ("MONDO:8", DISEASE, "disease eight"),
        ("MONDO:9", DISEASE, "disease one, non-human animal"),
        ("HP:1", FEATURE, "phenotype one"),
        ("HP:2", FEATURE, "phenotype two"),
        ("HGNC:1", GENE, "gene one"),
    ]  # note: HP:9 is intentionally NOT a node, to test the LEFT JOIN
    edges = [
        ("MONDO:1", "HP:1", PHENO),
        ("MONDO:1", "HP:2", PHENO),
        ("MONDO:1", "HP:9", PHENO),
        ("HGNC:1", "MONDO:1", CAUSES),
        ("MONDO:1", "MONDO:2", SUBCLASS),
        ("MONDO:3", "MONDO:1", SUBCLASS),
        ("MONDO:2", "HP:1", PHENO),
    ]
    con.executemany("INSERT INTO nodes VALUES (?, ?, ?)", nodes)
    con.executemany("INSERT INTO edges VALUES (?, ?, ?)", edges)
    return con


def cand(id_, category, sim):
    """An anchor candidate tuple: (id, category, text, similarity)."""
    return (id_, category, f"text of {id_}", sim)


# --- traverse: direction handling --------------------------------------------------

def test_Traverse_WHEN_anchor_is_subject_SHOULD_return_objects_as_out(graph):
    rows = traverse(graph, "MONDO:1", PHENO)
    by_id = {r[0]: r for r in rows}
    assert set(by_id) == {"HP:1", "HP:2", "HP:9"}
    assert all(r[3] == "out" for r in rows)


def test_Traverse_WHEN_anchor_is_object_SHOULD_return_subjects_as_in(graph):
    rows = traverse(graph, "MONDO:1", CAUSES)
    assert {r[0] for r in rows} == {"HGNC:1"}
    assert rows[0][3] == "in"


def test_Traverse_WHEN_predicate_is_symmetric_SHOULD_return_both_directions(graph):
    rows = traverse(graph, "MONDO:1", SUBCLASS)
    dirs = {r[0]: r[3] for r in rows}
    assert dirs == {"MONDO:2": "out", "MONDO:3": "in"}


def test_Traverse_WHEN_neighbour_absent_from_nodes_SHOULD_keep_it_with_null_name(graph):
    rows = traverse(graph, "MONDO:1", PHENO)
    hp9 = next(r for r in rows if r[0] == "HP:9")
    assert hp9[2] is None  # LEFT JOIN: name is null, but the edge is NOT dropped


def test_Traverse_WHEN_no_edge_of_predicate_SHOULD_return_empty(graph):
    assert traverse(graph, "MONDO:1", TREATS) == []


# --- edge_count_of: either-side counting -------------------------------------------

def test_EdgeCount_WHEN_anchor_on_either_side_SHOULD_count_both(graph):
    assert edge_count_of(graph, "MONDO:1", [PHENO]) == 3  # three out-edges
    assert edge_count_of(graph, "MONDO:1", [CAUSES]) == 1  # one in-edge


def test_EdgeCount_WHEN_disease_lacks_predicate_SHOULD_be_zero(graph):
    assert edge_count_of(graph, "MONDO:9", [PHENO]) == 0


# --- disambiguate: the rebuilt selection rule --------------------------------------

def test_Disambiguate_WHEN_top_hits_are_wrong_category_or_edgeless_SHOULD_skip_them(graph):
    # phenotype node (wrong category) then near-synonym disease with 0 edges, then hub.
    cands = [
        cand("HP:1", FEATURE, 0.9),
        cand("MONDO:9", DISEASE, 0.8),
        cand("MONDO:1", DISEASE, 0.7),
    ]
    rank, chosen, count = disambiguate(graph, cands, [PHENO])
    assert chosen[0] == "MONDO:1"
    assert rank == 2 and count == 3


def test_Disambiguate_WHEN_earlier_disease_has_an_edge_SHOULD_beat_a_bigger_later_hub(graph):
    # MONDO:2 (1 phenotype edge) ranks above MONDO:1 (3): first-with-edge wins, NOT max.
    cands = [cand("MONDO:2", DISEASE, 0.9), cand("MONDO:1", DISEASE, 0.8)]
    rank, chosen, count = disambiguate(graph, cands, [PHENO])
    assert chosen[0] == "MONDO:2" and rank == 0 and count == 1


def test_Disambiguate_WHEN_no_disease_has_the_edge_SHOULD_fall_back_to_first_disease(graph):
    cands = [
        cand("HP:1", FEATURE, 0.9),
        cand("MONDO:9", DISEASE, 0.8),
        cand("MONDO:8", DISEASE, 0.7),
    ]
    rank, chosen, count = disambiguate(graph, cands, [PHENO])
    assert chosen[0] == "MONDO:9" and rank == 1 and count == 0


def test_Disambiguate_WHEN_no_candidate_is_a_disease_SHOULD_fall_back_to_top_hit(graph):
    cands = [cand("HP:1", FEATURE, 0.9), cand("HGNC:1", GENE, 0.8)]
    rank, chosen, _count = disambiguate(graph, cands, [PHENO])
    assert chosen[0] == "HP:1" and rank == 0


def test_Disambiguate_WHEN_no_candidates_SHOULD_return_none(graph):
    assert disambiguate(graph, [], [PHENO]) == (None, None, 0)


# --- select_within_margin: the predicate-pick rule ---------------------------------

def test_SelectWithinMargin_WHEN_one_clear_winner_SHOULD_return_only_it():
    assert select_within_margin([("a", 0.90), ("b", 0.50)], 0.05) == ["a"]


def test_SelectWithinMargin_WHEN_a_cluster_ties_near_top_SHOULD_return_the_cluster():
    ranked = [("a", 0.90), ("b", 0.88), ("c", 0.50)]
    assert select_within_margin(ranked, 0.05) == ["a", "b"]


def test_SelectWithinMargin_WHEN_score_is_exactly_at_the_boundary_SHOULD_include_it():
    # b sits exactly margin below a (0.90 - 0.05 = 0.85); the cutoff is inclusive.
    assert select_within_margin([("a", 0.90), ("b", 0.85)], 0.05) == ["a", "b"]


def test_SelectWithinMargin_WHEN_score_is_just_below_boundary_SHOULD_exclude_it():
    assert select_within_margin([("a", 0.90), ("b", 0.8499)], 0.05) == ["a"]
