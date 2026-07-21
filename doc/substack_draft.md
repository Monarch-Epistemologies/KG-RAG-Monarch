# KG-RAG-Monarch — design notebook (substack draft)

Running record of *why* v2 is shaped the way it is. Written before the code.
This is an outline — sections are the questions v2 has to answer, in roughly the
order they bite. Prose to follow.

---

## 1. What "beyond EDS" means mechanically

From a single seed set to what? More disease seeds, k-hop expansion from seeds, or
the whole node set. This sizes the corpus, which drives everything downstream.

Start from what v1 actually did, because the shape of the question comes straight
out of it. The EDS subgraph was built by matching 57 MONDO terms whose names carry
"Ehlers-Danlos syndrome", then keeping every edge in which one of those 57 appears
as subject or object. That is 1,900 edges, and the entities on the far ends of them
come to 833 nodes with text. So v1 is a name-matched seed set plus exactly one hop,
and its corpus is under a thousand documents — small enough that every cost question
downstream had an obvious answer.

The full dump those 833 nodes were carved out of holds 1,462,595 nodes and
15,211,572 edges. That is the far end of the range. Between the two sit the three
candidate moves, and they are not variations on a theme — they scale differently
and they fail differently.

Adding more disease seeds keeps the v1 mechanism and multiplies it. Corpus size
grows roughly in proportion to how many seeds are added, because each new disease
drags in its own genes and phenotypes with only modest overlap. It is predictable,
and it is the only one of the three where a target corpus size can be chosen in
advance. What it does not do is teach much: it is v1 run more times.

Widening the hop radius is the move that looks incremental and is not. Going from
one hop to two means the neighbors of the neighbors, and biomedical graphs have hub
nodes — a common phenotype term, a frequently annotated gene — with degree in the
thousands. One pass through a hub and the frontier stops being a neighborhood.
Two hops from 57 seeds could plausibly land anywhere between tens of thousands of
nodes and a large fraction of the whole graph, and which one it is cannot be
guessed. It has to be measured on the real dump before it can be committed to.
That measurement is cheap — it is a query over the edge table, no embedding
involved — and it should happen early, because the answer decides whether hop
expansion is a usable knob or a trap.

Taking the whole node set removes the filter entirely, and there is something
appealing about that: no seed choice to defend, no hop radius to justify, no
question about whether the answer was in the subgraph or got cut away. The
retrieval quality question becomes clean, because the corpus is the graph. The
cost is that 1.46M documents is where the Mac's limits actually start to bite,
which is section 2's problem.

The honest read is that seeds and hops are ways of avoiding the whole graph, and
the reason to avoid the whole graph is cost rather than principle. So the first
thing to measure is not which subgraph to build — it is what the whole graph costs.
If 1.46M nodes turn out to be patiently embeddable into vectors on this machine,
the subgraph question mostly dissolves, and the interesting scaling question moves
to what we embed rather than how much of the graph we keep.

### Measured: eight diseases

The hop-expansion prediction above was wrong, and it is worth leaving in place so
the correction has something to correct. Running v1's exact mechanics — MONDO name
substring for the seeds, then every edge incident to that set — over eight diseases
chosen to span rare monogenic, multi-subtype and common complex:

| disease | seeds | h1 nodes | h1 edges | h2 nodes | h2 edges | top hub in h1 |
|---|---|---|---|---|---|---|
| Ehlers-Danlos syndrome | 57 | 832 | 1,900 | 33,310 | 269,705 | Autosomal recessive inheritance (8,080) |
| Noonan syndrome | 21 | 565 | 1,275 | 32,353 | 261,158 | Autosomal recessive inheritance (8,080) |
| amyotrophic lateral sclerosis | 48 | 476 | 935 | 33,440 | 138,260 | Autosomal recessive inheritance (8,080) |
| Parkinson disease | 45 | 514 | 914 | 31,792 | 110,051 | Autosomal recessive inheritance (8,080) |
| Marfan syndrome | 5 | 329 | 465 | 21,322 | 86,654 | Autosomal dominant inheritance (6,341) |
| Rett syndrome | 4 | 232 | 308 | 19,975 | 77,333 | Global developmental delay (7,276) |
| cystic fibrosis | 9 | 545 | 565 | 24,104 | 59,533 | Autosomal recessive inheritance (8,080) |
| type 2 diabetes mellitus | 6 | 224 | 240 | 14,709 | 24,988 | Autosomal dominant inheritance (6,341) |

These eight are a convenience sample, not a survey — there are 29,866 non-deprecated
MONDO terms with at least one edge in this dump, and these were chosen by hand to
span shapes that seemed likely to differ. What follows holds for them; the
distribution over all 29,866 is a separate question.

Two hops does not run away. The worst case here is 270k edges and the range across
all eight is 25k to 270k — nowhere near a large fraction of a 15.2M-edge graph.
Taken together as one subgraph they deduplicate hard: the union of all eight at two
hops is 529,380 edges, roughly half the 1.03M the per-disease rows sum to, because
these diseases share phenotype and gene neighbours. Half a million triples sits
inside the budget derived in section 2 with room to spare, even at 768 dimensions.
The trap I predicted is not there at this radius.

The hub mechanism is real, but the clean fix I expected is not. The highest-degree
node in each one-hop frontier is an inheritance-mode term for six of the eight —
"Autosomal recessive inheritance", degree 8,080, in five of them — and that suggested
a short exclusion list of semantically empty hubs. Measured, dropping every
`has_mode_of_inheritance` edge takes the union's two-hop corpus from 529,380 to
514,484, a three percent saving. The reason is visible one level down the hub list:
only two of the top twenty frontier hubs are inheritance terms. The rest are generic
but genuine phenotypes — Global developmental delay at 7,276, Seizure at 6,094,
Intellectual disability at 5,953, Scoliosis at 3,952 — and highly connected genes
such as PRKN at 6,787, KRAS at 4,813 and VCP at 3,233. Those attach through
`has_phenotype` and `interacts_with`, the same predicates that carry the signal, so
no predicate-level cut removes the fan-out without removing content. Excluding
`interacts_with` as well takes the union to 446,762, a sixteen percent saving, and
that one costs real protein-interaction data rather than noise.

So hub surgery is a tuning knob to keep in reserve, not a prerequisite. At this
radius the corpus already fits, and the argument for cutting hubs has to be made on
retrieval quality rather than on size.

Seed count is a weak predictor of subgraph size. EDS matches 57 seeds and Marfan 5,
a factor of eleven, but their one-hop node counts are 832 and 329, a factor of 2.5.
Rett matches four seeds and still reaches 232 nodes. Subtypes of the same disease
share most of their phenotype and gene neighbours, so multiplying seeds buys much
less corpus than it appears to — which weakens the first of the three moves above.

One row needs a caveat before anyone leans on it. Type 2 diabetes coming out
smallest does not mean the graph knows little about it. The seed selector matches a
literal substring against the node's `name` column only — not synonyms, not xrefs,
not the subclass hierarchy. There are 162 MONDO terms with "diabetes" in the name and
only 6 containing "type 2 diabetes mellitus". EDS scores well here because its
subtype terms nearly all spell the parent name out in full; diabetes does not. That
row measures the reach of the name match, not the disease's presence in the graph,
and it is the first sign that seed selection deserves a better mechanism than
substring matching — most likely the MONDO hierarchy itself.

### Measured: all 29,866 diseases

Eight hand-picked diseases can only support so much, so the same shape query was run
over every non-deprecated MONDO term in the dump that has at least one edge. The unit
is different here — one MONDO term as the seed, rather than a name-matched family of
subtypes — so these numbers are not comparable row-for-row with the table above.

Two-hop edge counts are reported as the sum of frontier-node degrees, which
double-counts any edge with both ends in the frontier. On a random sample of twelve
diseases the exact count and the bound agreed to within a tenth of a percent, so the
distribution can be read at face value.

|  | h1 nodes | h2 edges |
|---|---|---|
| p50 | 4 | 420 |
| p75 | 16 | 9,823 |
| p90 | 38 | 32,092 |
| p95 | 56 | 50,214 |
| p99 | 114 | 88,608 |
| p99.9 | 278 | 140,775 |
| max | 2,683 | 202,295 |

No single disease can blow the budget. The largest two-hop neighbourhood in all of
MONDO is 202,295 edges — a tenth of the two-million-triple ceiling — and 99.4% of
diseases stay under 100,000. Not one exceeds half a million. The hop-radius worry
that opened this section is not merely smaller than predicted; at one seed it cannot
be the binding constraint at all.

What binds is the number of seeds, and it binds gently because neighbourhoods
overlap. The eight-disease union came to 529,380 edges against a 1.03M sum of its
parts, a discount of about half. Applying that discount to p90-sized diseases, a
two-million-triple budget buys on the order of a hundred diseases at two hops; at
median sizes it buys thousands. Section 1's question is therefore not which radius to
choose but how many seeds to take, which was the most tractable of the three moves
from the start.

The distribution also indicts the sample above. The median disease has four
neighbours and 420 two-hop edges. All eight chosen by hand sit far into the tail,
because well-studied diseases are what comes to mind when picking examples. That
skew matters most for the whole-graph option: a 1.46M-node corpus is dominated by
sparsely annotated terms whose text is little more than a label, and how retrieval
behaves over a corpus of mostly-bare documents is a quality question that no amount
of runtime measurement will answer.

## 2. What we embed — nodes vs. triples

1.46M nodes vs. 15.2M triples. The single biggest lever on runtime and on whether
the Mac stays viable.

The unit we embed into a vector is the unit we retrieve. v1 embedded nodes: for each
entity, its name, its synonyms and its description concatenated into one document,
which meant a question returned entities and the graph structure had to be walked
separately to get from an entity to a fact. The alternative is to embed triples —
one document per edge, built from the subject's name, a readable form of the
predicate and the object's name — so that a question returns assertions directly,
and "what connects Ehlers-Danlos syndrome to joint dislocation" is answered by
nearest-neighbor search rather than by traversal.

That is a real difference in what the retrieval channel can do on its own, and it
is not free. Each edge in the dump is one triple, so the two corpora are one document
per node against one document per edge: 1,462,595 documents against 15,211,572, a
factor of about 10.4. Every cost in the pipeline moves by that factor, and two of
them matter enough to decide the question.

The first is the embedding run itself. Embedding into vectors is a single forward
pass per document with no gradient, so the cost is linear in document count and the
useful figure is documents per second on this machine — which is exactly what has
not been measured yet, because v1's 833 documents finished before the question could
come up. Whatever that rate turns out to be, the triple corpus takes ten times as
long as the node corpus, and it takes that long again on every re-embedding. Section
3 is about swapping the model for a biomedical one, and a model swap means
re-embedding every row from scratch. So the tenfold factor is not paid once; it is
paid once per model we want to compare.

The second is memory, and here the arithmetic is unforgiving. At MiniLM's 384
dimensions and four bytes per float, node-level embedding produces about 2.1 GiB of
vectors and triple-level about 21.8 GiB. The 2.1 GiB fits in this machine's 16 GB of
unified memory with room to work. The 21.8 GiB does not fit at all, and unified
memory means the model, the OS and everything else are drawing on the same pool.
Storing the vectors is not the problem — DuckDB is perfectly happy to keep them on
disk. The problem arrives in section 4, when brute-force cosine gives way to an
approximate-nearest-neighbor index, because building such an index generally wants
the vectors resident. A corpus that cannot be held in RAM cannot have an in-RAM
index built over it, and that is a hard wall rather than a slow path.

That makes triple-level embedding over the full graph the clearest candidate for the
v3 tripwire in section 5 — not because it is slow, but because it does not fit. It
also means the two forks of this section are not symmetric. Node-level embedding
over the whole graph is a patience question and the machine can answer it.
Triple-level embedding over the whole graph is a capacity question and the machine
cannot, so if we want assertion-level retrieval on this hardware it has to come with
a subgraph from section 1, which is where the two sections meet.

A third option is worth naming before committing: embed nodes, and reach facts by
traversal from retrieved entities, which is what v1 already built in its second
sub-project. That keeps the corpus at 1.46M and buys assertion-level answers with
graph walks instead of vectors. Whether it is a substitute for triple embedding or a
weaker approximation of it is an evaluation question, and it is cheap enough to
answer that it should be answered before paying the tenfold cost.

## 3. Which embedding model

Quality through training, not brute-force size: general vs. biomedical
(MedCPT / BioLORD / SapBERT). The quality/runtime tables as the evidence.

_(draft here)_

## 4. Retrieval at scale

When brute-force DuckDB cosine gives way to an ANN index, and the 16GB in-RAM index
ceiling.

_(draft here)_

## 5. The v3 tripwire

The measured condition that ends the native-Mac era and justifies Docker + RunPod.

_(draft here)_
