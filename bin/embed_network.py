#!/usr/bin/env python3
"""Build the structural (network) embedding — the third retrieval method.

Where the first two methods embed content — node-text and triple-text retrieval embed
what is written about a node — this one embeds a node by its POSITION in the graph. The
recipe is node2vec: take many random walks over the edges, treat each walk as a sentence
of node IDs, and train skip-gram (word2vec) on it. Nodes that co-occur along walks —
structurally near — land near each other in the vector space, regardless of whether
their names share any words.

Two walk schemes, chosen with --scheme:

  uniform  — at each step the next node is a uniform random neighbour. node2vec's
             p = q = 1 case (a.k.a. DeepWalk). Every node is embedded.
  metapath — walks follow a category cycle from config (e.g. Disease-PhenotypicFeature),
             so a disease is co-located with its phenotypes / genes / drugs specifically,
             not blended with every node type. metapath2vec, for a heterogeneous graph.
             Only nodes of a scheme's categories are embedded — which is exactly the
             answer space (diseases and their phenotype/gene/drug neighbours).

Runs under the dedicated python3.13 venv (venv313): gensim has no wheel for the main
venv's 3.14 and its C extension will not compile there. Reads data/graph.duckdb and
writes vectors to an --out .duckdb; the eval reads that back under the main venv, reusing
the SapBERT anchor. The two interpreters never share a process — they hand off by file.

  <out>.duckdb
    node_vectors(id, category, embedding FLOAT[dim])   # one row per embedded node

Run (patient, one-time, CPU):
  venv313/bin/python3 bin/embed_network.py                                   # uniform
  venv313/bin/python3 bin/embed_network.py --scheme metapath \\
      --out data/network_metapath.duckdb                                     # typed
"""

import argparse
import pathlib
import random
import time

import duckdb
import numpy as np
import yaml

import shape_common as sc

# gensim is imported lazily inside main(): it lives only in venv313, but the graph and
# walk logic below is pure numpy/duckdb and stays importable (and unit-testable) under
# the main venv, which has no gensim.

CONFIG = sc.PROJECT_HOME / "config" / "network_embed.yaml"
GRAPH_DB = sc.PROJECT_HOME / "data" / "graph.duckdb"
OUT_DB = sc.PROJECT_HOME / "data" / "network.duckdb"
WALKS = sc.PROJECT_HOME / "data" / "walks.tmp"  # streamed corpus; data/ is gitignored


def load_config(path=CONFIG):
    with open(path) as fh:
        return yaml.safe_load(fh)


def build_vocab(con):
    """vocab[i] = node id at integer index i (every node appearing in an edge), and the
    inverse id->index map. This is the structural node set the walks and vectors use."""
    vocab = [
        r[0]
        for r in con.execute(
            """SELECT DISTINCT id FROM (
                   SELECT subject AS id FROM edges
                   UNION SELECT object FROM edges)
               ORDER BY id"""
        ).fetchall()
    ]
    return vocab, {v: i for i, v in enumerate(vocab)}


def _edge_arcs(con, idx):
    """The edge list as index pairs, both directions (undirected walks)."""
    e = con.execute("SELECT subject, object FROM edges").fetchnumpy()
    s = np.fromiter((idx[x] for x in e["subject"]), dtype=np.int32, count=len(e["subject"]))
    o = np.fromiter((idx[x] for x in e["object"]), dtype=np.int32, count=len(e["object"]))
    return np.concatenate([s, o]), np.concatenate([o, s])


def _csr(src, dst, n):
    """Standard CSR: neighbours of node i are indices[indptr[i]:indptr[i+1]]."""
    order = np.argsort(src, kind="stable")
    indices = dst[order]
    indptr = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(np.bincount(src, minlength=n), out=indptr[1:])
    return indptr, indices


def build_adjacency(con):
    """Undirected CSR adjacency over every node that appears in an edge."""
    vocab, idx = build_vocab(con)
    src, dst = _edge_arcs(con, idx)
    indptr, indices = _csr(src, dst, len(vocab))
    return vocab, indptr, indices


def category_codes(con, vocab):
    """Per-index category as small int codes (arr[i]), plus the {category_string: code}
    map. Edge-only endpoints with no node row get -1 (no category, unreachable by any
    metapath). Codes are assigned in first-seen order over vocab."""
    cat_of = dict(con.execute("SELECT id, category FROM nodes").fetchall())
    codes = {}
    arr = np.full(len(vocab), -1, dtype=np.int32)
    for i, v in enumerate(vocab):
        c = cat_of.get(v)
        if c is None:
            continue
        arr[i] = codes.setdefault(c, len(codes))
    return arr, codes


def build_typed_adjacency(con, idx, cats_arr, target_codes):
    """One CSR per target category: typed[C] holds, for every node, its neighbours whose
    category is C. Precomputed (rather than filtered per step) so a metapath step from a
    hub stays O(1) instead of O(degree)."""
    src, dst = _edge_arcs(con, idx)
    dst_code = cats_arr[dst]
    n = len(cats_arr)
    return {C: _csr(src[dst_code == C], dst[dst_code == C], n) for C in target_codes}


def generate_walks(indptr, indices, num_walks, walk_length, seed, out_path=WALKS):
    """Write num_walks uniform random walks from each node to out_path, one per line,
    tokens = integer node indices. Streamed to disk so the corpus never sits in RAM;
    gensim reads it back multithreaded via corpus_file."""
    rng = random.Random(seed)
    randrange = rng.randrange
    ptr = indptr.tolist()  # python ints: faster than numpy scalar indexing in the hot loop
    nbr = indices.tolist()
    n = len(ptr) - 1

    written = 0
    with open(out_path, "w") as fh:
        buf = []
        for start in range(n):
            for _ in range(num_walks):
                walk = [start]
                cur = start
                for _ in range(walk_length - 1):
                    lo, hi = ptr[cur], ptr[cur + 1]
                    if hi == lo:  # dead end (no neighbours)
                        break
                    cur = nbr[randrange(lo, hi)]
                    walk.append(cur)
                buf.append(" ".join(map(str, walk)))
            if len(buf) >= 100_000:
                fh.write("\n".join(buf) + "\n")
                written += len(buf)
                buf.clear()
        if buf:
            fh.write("\n".join(buf) + "\n")
            written += len(buf)
    return written


def generate_metapath_walks(typed, cats_arr, schemes, num_walks, walk_length, seed, out_path=WALKS):
    """Write metapath-constrained walks. Each scheme is a cycle of category codes; a walk
    starts at a node of the scheme's first category and at each step moves to a uniform
    random neighbour of the next category in the cycle. All schemes' walks share one
    corpus, so a disease ends up near its phenotypes AND its genes AND its drugs."""
    rng = random.Random(seed)
    randrange = rng.randrange
    tptr = {C: p.tolist() for C, (p, _) in typed.items()}
    tnbr = {C: i.tolist() for C, (_, i) in typed.items()}
    cats = cats_arr.tolist()

    written = 0
    with open(out_path, "w") as fh:
        buf = []
        for scheme in schemes:
            start_code, length = scheme[0], len(scheme)
            for start in range(len(cats)):
                if cats[start] != start_code:
                    continue
                for _ in range(num_walks):
                    walk = [start]
                    cur = start
                    for step in range(walk_length - 1):
                        nxt = scheme[(step + 1) % length]
                        ptr, nbr = tptr[nxt], tnbr[nxt]
                        lo, hi = ptr[cur], ptr[cur + 1]
                        if hi == lo:  # no neighbour of the required category
                            break
                        cur = nbr[randrange(lo, hi)]
                        walk.append(cur)
                    buf.append(" ".join(map(str, walk)))
                if len(buf) >= 100_000:
                    fh.write("\n".join(buf) + "\n")
                    written += len(buf)
                    buf.clear()
        if buf:
            fh.write("\n".join(buf) + "\n")
            written += len(buf)
    return written


def write_vectors(model, vocab, cat_map, dim, out_db):
    """Persist one row per embedded node, mirroring the anchor store's schema so the eval
    can score it with array_cosine_similarity like the others. Inserts the whole matrix in
    one Arrow batch — a row-by-row executemany took tens of minutes for 300k FLOAT[dim]
    rows and left long builds exposed to being killed mid-write."""
    import pyarrow as pa  # venv313 only, like gensim

    if out_db.exists():
        out_db.unlink()  # derived, never hand-edited
    ids = [vocab[int(k)] for k in model.wv.index_to_key]
    tbl = pa.table({
        "id": pa.array(ids),
        "category": pa.array([cat_map.get(i) for i in ids], type=pa.string()),
        "embedding": pa.FixedSizeListArray.from_arrays(model.wv.vectors.reshape(-1), dim),
    })
    out = duckdb.connect(str(out_db))
    out.register("vecs", tbl)
    out.execute(
        f"CREATE TABLE node_vectors AS "
        f"SELECT id, category, embedding::FLOAT[{dim}] AS embedding FROM vecs"
    )
    n = out.execute("SELECT count(*) FROM node_vectors").fetchone()[0]
    out.close()
    return n


def main():
    from gensim.models import Word2Vec  # venv313 only; see module header

    ap = argparse.ArgumentParser(description="Build the structural (network) embedding.")
    ap.add_argument("--config", default=CONFIG)
    ap.add_argument("--out", default=str(OUT_DB), help="output .duckdb (relative to repo root)")
    ap.add_argument("--graph", default=str(GRAPH_DB), help="input graph .duckdb (for held-out link-prediction training)")
    ap.add_argument("--scheme", choices=["uniform", "metapath"], help="override config walk_scheme")
    args = ap.parse_args()

    cfg = load_config(args.config)
    scheme = args.scheme or cfg.get("walk_scheme", "uniform")
    out_db = pathlib.Path(args.out)
    if not out_db.is_absolute():
        out_db = sc.PROJECT_HOME / out_db
    walks = out_db.with_suffix(".walks.tmp")  # unique per output, so runs can coexist
    con = duckdb.connect(str(args.graph), read_only=True)

    t0 = time.time()
    if scheme == "uniform":
        vocab, indptr, indices = build_adjacency(con)
        print(f"adjacency: {len(vocab)} nodes, {len(indices)} arcs ({time.time() - t0:.0f}s)")
        t0 = time.time()
        n_walks = generate_walks(
            indptr, indices, cfg["num_walks"], cfg["walk_length"], cfg["seed"], out_path=walks
        )
    else:
        vocab, idx = build_vocab(con)
        cats_arr, code_of = category_codes(con, vocab)
        schemes = [[code_of[c] for c in mp] for mp in cfg["metapaths"]]
        target_codes = sorted({c for mp in schemes for c in mp})
        typed = build_typed_adjacency(con, idx, cats_arr, target_codes)
        arcs = sum(len(i) for _, i in typed.values())
        print(f"typed adjacency: {len(vocab)} nodes, {len(typed)} categories, "
              f"{arcs} typed arcs ({time.time() - t0:.0f}s)")
        t0 = time.time()
        n_walks = generate_metapath_walks(
            typed, cats_arr, schemes, cfg["num_walks"], cfg["walk_length"], cfg["seed"],
            out_path=walks,
        )
    print(f"walks ({scheme}): {n_walks} written ({time.time() - t0:.0f}s)")

    t0 = time.time()
    model = Word2Vec(
        corpus_file=str(walks),
        vector_size=cfg["dim"],
        window=cfg["window"],
        min_count=cfg["min_count"],
        sg=1,  # skip-gram
        workers=cfg["workers"],
        epochs=cfg["epochs"],
        seed=cfg["seed"],
    )
    print(f"trained: {len(model.wv)} vectors ({len(model.wv) / len(vocab):.0%} of nodes), "
          f"dim {cfg['dim']} ({time.time() - t0:.0f}s)")
    assert 0 < len(model.wv) <= len(vocab), f"vectors {len(model.wv)} vs nodes {len(vocab)}"

    cat_map = dict(con.execute("SELECT id, category FROM nodes").fetchall())
    n = write_vectors(model, vocab, cat_map, cfg["dim"], out_db)
    walks.unlink()
    try:
        shown = out_db.relative_to(sc.PROJECT_HOME)  # temp paths (sweep) live outside the repo
    except ValueError:
        shown = out_db
    print(f"{shown}: {n} node vectors written")


if __name__ == "__main__":
    main()
