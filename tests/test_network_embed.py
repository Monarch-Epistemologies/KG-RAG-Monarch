"""Unit tests for the network (structural) embedding's non-model logic
(bin/{embed_network,eval_network}.py).

UNIT tests: the graph→walks build (build_adjacency, generate_walks) and the eval's
anchor/nearest rules run against a hand-built tiny graph and a tiny in-memory vector
table — no gensim, no SapBERT, no multi-GB stores. The skip-gram training itself and
the end-to-end score need a real model and corpus; those are integration, scored by
bin/eval_network.py, and deliberately not here. What IS unit-testable is where the
method's behaviour actually lives: that walks respect undirected adjacency, that
edge-only endpoints get embedded, that the anchor picks the disease namespace, and
that nearest excludes the anchor and honours the budget.

embed_network imports gensim lazily (venv313 only), so this module imports cleanly
under the main venv where the suite runs.
"""

import duckdb
import numpy as np

from embed_network import (
    build_adjacency,
    build_typed_adjacency,
    build_vocab,
    category_codes,
    generate_metapath_walks,
    generate_walks,
)
from eval_network import nearest, pick_anchor

DISEASE = "biolink:Disease"
PHENO = "biolink:PhenotypicFeature"
GENE = "biolink:Gene"


def make_edges(pairs):
    con = duckdb.connect()
    con.execute("CREATE TABLE edges (subject VARCHAR, object VARCHAR, predicate VARCHAR)")
    con.executemany(
        "INSERT INTO edges VALUES (?, ?, 'p')", [(s, o) for s, o in pairs]
    )
    return con


def make_graph(nodes, pairs):
    """nodes: [(id, category)]; pairs: [(subject, object)]."""
    con = make_edges(pairs)
    con.execute("CREATE TABLE nodes (id VARCHAR, category VARCHAR, name VARCHAR)")
    con.executemany("INSERT INTO nodes VALUES (?, ?, '')", nodes)
    return con


def neighbours(vocab, indptr, indices, node):
    i = vocab.index(node)
    return sorted(vocab[indices[j]] for j in range(indptr[i], indptr[i + 1]))


# --- build_adjacency ---------------------------------------------------------------

def test_BuildAdjacency_WHEN_edge_is_directed_SHOULD_make_it_undirected():
    con = make_edges([("A", "B")])
    vocab, indptr, indices = build_adjacency(con)
    assert neighbours(vocab, indptr, indices, "A") == ["B"]
    assert neighbours(vocab, indptr, indices, "B") == ["A"]  # reverse arc added


def test_BuildAdjacency_WHEN_endpoint_only_appears_as_object_SHOULD_be_in_vocab():
    # D never appears as a subject; structural vocab is the union of both endpoints.
    con = make_edges([("A", "B"), ("A", "D")])
    vocab, _indptr, _indices = build_adjacency(con)
    assert set(vocab) == {"A", "B", "D"}


def test_BuildAdjacency_WHEN_indptr_indices_used_SHOULD_slice_to_a_nodes_neighbours():
    con = make_edges([("A", "B"), ("A", "C"), ("D", "A")])
    vocab, indptr, indices = build_adjacency(con)
    assert neighbours(vocab, indptr, indices, "A") == ["B", "C", "D"]
    assert len(indices) == 6  # 3 edges, both directions
    assert indptr[-1] == len(indices)


def test_BuildAdjacency_WHEN_a_parallel_edge_exists_SHOULD_keep_the_multiplicity():
    # Two A–B edges bias a walk toward B; adjacency must not dedupe them.
    con = make_edges([("A", "B"), ("A", "B")])
    vocab, indptr, indices = build_adjacency(con)
    assert neighbours(vocab, indptr, indices, "A") == ["B", "B"]


# --- generate_walks ----------------------------------------------------------------

def test_GenerateWalks_WHEN_run_SHOULD_write_num_walks_lines_per_node(tmp_path):
    con = make_edges([("A", "B"), ("B", "C")])
    vocab, indptr, indices = build_adjacency(con)
    out = tmp_path / "w.txt"
    written = generate_walks(indptr, indices, num_walks=3, walk_length=5, seed=7, out_path=out)
    lines = out.read_text().strip().splitlines()
    assert written == len(lines) == len(vocab) * 3


def test_GenerateWalks_WHEN_stepping_SHOULD_only_follow_real_undirected_edges(tmp_path):
    con = make_edges([("A", "B"), ("A", "C"), ("D", "A")])
    vocab, indptr, indices = build_adjacency(con)
    undirected = {("A", "B"), ("B", "A"), ("A", "C"), ("C", "A"), ("D", "A"), ("A", "D")}
    out = tmp_path / "w.txt"
    generate_walks(indptr, indices, num_walks=5, walk_length=10, seed=7, out_path=out)
    for line in out.read_text().strip().splitlines():
        walk = [vocab[int(t)] for t in line.split()]
        for a, b in zip(walk, walk[1:]):
            assert (a, b) in undirected


def test_GenerateWalks_WHEN_a_node_has_no_neighbours_SHOULD_emit_a_length_one_walk(tmp_path):
    # build_adjacency never yields an isolated node (every vocab node came from an edge),
    # so the dead-end branch is exercised with a hand-crafted CSR: node 2 has no arcs.
    indptr = np.array([0, 1, 2, 2])   # 0->[1], 1->[0], 2->[] (isolated)
    indices = np.array([1, 0])
    out = tmp_path / "w.txt"
    generate_walks(indptr, indices, num_walks=1, walk_length=5, seed=1, out_path=out)
    walks = [ln.split() for ln in out.read_text().strip().splitlines()]
    by_start = {w[0]: w for w in walks}
    assert by_start["2"] == ["2"]          # dead end: walk is just the start node
    assert len(by_start["0"]) == 5         # connected node walks the full length


def test_GenerateWalks_WHEN_same_seed_SHOULD_be_deterministic(tmp_path):
    con = make_edges([("A", "B"), ("A", "C"), ("B", "C")])
    vocab, indptr, indices = build_adjacency(con)
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    generate_walks(indptr, indices, num_walks=4, walk_length=6, seed=7, out_path=a)
    generate_walks(indptr, indices, num_walks=4, walk_length=6, seed=7, out_path=b)
    assert a.read_text() == b.read_text()


# --- category_codes & typed adjacency (metapath walks) -----------------------------

def test_CategoryCodes_WHEN_endpoint_has_no_node_row_SHOULD_code_it_minus_one():
    # G appears only as an edge object, with no row in nodes: it has no category.
    con = make_graph([("A", DISEASE), ("B", PHENO)], [("A", "B"), ("A", "G")])
    vocab, _idx = build_vocab(con)
    arr, codes = category_codes(con, vocab)
    assert arr[vocab.index("G")] == -1
    assert arr[vocab.index("A")] == codes[DISEASE]


def test_BuildTypedAdjacency_WHEN_target_is_a_category_SHOULD_return_only_that_category():
    # A connects to two phenotypes and one gene; the phenotype-typed CSR of A omits G.
    con = make_graph(
        [("A", DISEASE), ("B", PHENO), ("C", PHENO), ("G", GENE)],
        [("A", "B"), ("A", "C"), ("A", "G")],
    )
    vocab, idx = build_vocab(con)
    arr, codes = category_codes(con, vocab)
    typed = build_typed_adjacency(con, idx, arr, [codes[PHENO], codes[GENE]])
    ai = vocab.index("A")
    p_ptr, p_idx = typed[codes[PHENO]]
    g_ptr, g_idx = typed[codes[GENE]]
    assert sorted(vocab[p_idx[j]] for j in range(p_ptr[ai], p_ptr[ai + 1])) == ["B", "C"]
    assert [vocab[g_idx[j]] for j in range(g_ptr[ai], g_ptr[ai + 1])] == ["G"]


def _metapath_walks(con, schemes_cats, **kw):
    import pathlib

    vocab, idx = build_vocab(con)
    arr, codes = category_codes(con, vocab)
    schemes = [[codes[c] for c in s] for s in schemes_cats]
    targets = sorted({c for s in schemes for c in s})
    typed = build_typed_adjacency(con, idx, arr, targets)
    out = pathlib.Path(kw.pop("out_path"))
    generate_metapath_walks(typed, arr, schemes, out_path=out, **kw)
    return vocab, [[vocab[int(t)] for t in ln.split()] for ln in out.read_text().splitlines()]


def test_GenerateMetapathWalks_WHEN_scheme_is_disease_pheno_SHOULD_only_start_at_diseases(tmp_path):
    con = make_graph(
        [("A", DISEASE), ("B", PHENO), ("C", PHENO), ("G", GENE)],
        [("A", "B"), ("A", "C"), ("A", "G")],
    )
    _vocab, walks = _metapath_walks(
        con, [[DISEASE, PHENO]], num_walks=3, walk_length=6, seed=7, out_path=tmp_path / "w.txt"
    )
    assert {w[0] for w in walks} == {"A"}  # only the disease starts a D-P walk


def test_GenerateMetapathWalks_WHEN_stepping_SHOULD_alternate_the_scheme_categories(tmp_path):
    con = make_graph(
        [("A", DISEASE), ("B", PHENO), ("C", PHENO), ("G", GENE)],
        [("A", "B"), ("A", "C"), ("A", "G")],
    )
    _vocab, walks = _metapath_walks(
        con, [[DISEASE, PHENO]], num_walks=5, walk_length=8, seed=7, out_path=tmp_path / "w.txt"
    )
    for w in walks:
        # even positions are the disease, odd positions are phenotypes; G never appears
        assert all(w[i] == "A" for i in range(0, len(w), 2))
        assert all(w[i] in {"B", "C"} for i in range(1, len(w), 2))


def test_GenerateMetapathWalks_WHEN_same_seed_SHOULD_be_deterministic(tmp_path):
    con = make_graph(
        [("A", DISEASE), ("B", PHENO), ("C", PHENO)], [("A", "B"), ("A", "C")]
    )
    _v1, w1 = _metapath_walks(
        con, [[DISEASE, PHENO]], num_walks=4, walk_length=6, seed=3, out_path=tmp_path / "a.txt"
    )
    _v2, w2 = _metapath_walks(
        con, [[DISEASE, PHENO]], num_walks=4, walk_length=6, seed=3, out_path=tmp_path / "b.txt"
    )
    assert w1 == w2


# --- pick_anchor -------------------------------------------------------------------

def cand(id_):
    return (id_, "cat", "text", 0.5)


def test_PickAnchor_WHEN_a_mondo_hit_is_present_SHOULD_return_the_first_one():
    cands = [cand("HP:1"), cand("MONDO:5"), cand("MONDO:9")]
    assert pick_anchor(cands) == "MONDO:5"


def test_PickAnchor_WHEN_no_mondo_hit_SHOULD_fall_back_to_the_top_candidate():
    assert pick_anchor([cand("HP:1"), cand("HGNC:2")]) == "HP:1"


def test_PickAnchor_WHEN_no_candidates_SHOULD_return_none():
    assert pick_anchor([]) is None


# --- nearest -----------------------------------------------------------------------

def vector_table(dim=3):
    con = duckdb.connect()
    con.execute(f"CREATE TABLE node_vectors (id VARCHAR, category VARCHAR, embedding FLOAT[{dim}])")
    rows = [
        ("A", "d", [1.0, 0.0, 0.0]),
        ("B", "p", [0.9, 0.1, 0.0]),   # nearest to A
        ("C", "p", [0.0, 1.0, 0.0]),   # orthogonal to A
        ("D", "p", [-1.0, 0.0, 0.0]),  # opposite A
    ]
    con.executemany("INSERT INTO node_vectors VALUES (?, ?, ?)", rows)
    return con


def test_Nearest_WHEN_ranking_SHOULD_exclude_the_anchor_and_order_by_cosine():
    con = vector_table()
    assert nearest(con, "A", dim=3, budget=10) == ["B", "C", "D"]  # A itself absent


def test_Nearest_WHEN_budget_is_smaller_than_the_table_SHOULD_truncate():
    con = vector_table()
    assert nearest(con, "A", dim=3, budget=1) == ["B"]


def test_Nearest_WHEN_anchor_absent_from_the_space_SHOULD_return_empty():
    con = vector_table()
    assert nearest(con, "ZZZ", dim=3, budget=10) == []
