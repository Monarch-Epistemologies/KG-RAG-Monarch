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
substring for the seeds, then expansion by edges — over eight diseases chosen to
span rare monogenic, multi-subtype and common complex.

Before the numbers, one distinction that matters more than it sounds. An edge is
**incident** to a node set if at least one endpoint is inside it; **induced** if both
endpoints are. Incident edges are the discovery mechanism — following every edge
incident to the hop-1 nodes is what finds the hop-2 nodes — so they describe how far
a set reaches. Induced edges describe what a set contains. For a triple corpus the
induced count is the one that matters: if both endpoints are documents, the edge
between them is a fact the system can retrieve, and leaving it out means discarding
a fact between two things already kept. An incident edge whose far endpoint was not
kept is the opposite, a triple pointing at something the corpus cannot describe.

The two diverge sharply here, because a hop-2 frontier of thirty thousand phenotypes,
genes and variants is densely connected sideways for reasons unrelated to the seed
disease — subclass links between phenotypes, interactions between genes. Those edges
were never on the path outward, but they sit inside the set that was kept.

| disease | seeds | h1 nodes | h1 induced | h2 nodes | h2 induced | h2 incident | top hub in h1 |
|---|---|---|---|---|---|---|---|
| Ehlers-Danlos syndrome | 57 | 832 | 4,564 | 33,310 | 978,579 | 269,705 | Autosomal recessive inheritance (8,080) |
| Noonan syndrome | 21 | 565 | 5,991 | 32,353 | 1,533,957 | 261,158 | Autosomal recessive inheritance (8,080) |
| amyotrophic lateral sclerosis | 48 | 476 | 2,537 | 33,440 | 1,768,143 | 138,260 | Autosomal recessive inheritance (8,080) |
| Parkinson disease | 45 | 514 | 2,288 | 31,792 | 1,507,960 | 110,051 | Autosomal recessive inheritance (8,080) |
| cystic fibrosis | 9 | 545 | 1,045 | 24,104 | 810,762 | 59,533 | Autosomal recessive inheritance (8,080) |
| type 2 diabetes mellitus | 6 | 224 | 410 | 14,709 | 706,830 | 24,988 | Autosomal dominant inheritance (6,341) |
| Rett syndrome | 4 | 232 | 672 | 19,975 | 610,000 | 77,333 | Global developmental delay (7,276) |
| Marfan syndrome | 5 | 329 | 1,849 | 21,322 | 431,531 | 86,654 | Autosomal dominant inheritance (6,341) |

These eight are a convenience sample, not a survey — there are 29,866 non-deprecated
MONDO terms with at least one edge in this dump, and these were chosen by hand to
span shapes that seemed likely to differ. What follows holds for them; the
distribution over all 29,866 is a separate question.

One hop and two hops bracket the budget rather than both sitting under it. At one hop
a single disease family yields a few thousand triples — 410 for type 2 diabetes, 5,991
for Noonan — which is too small to exercise anything. At two hops the same families
yield between 431,531 and 1,768,143, and amyotrophic lateral sclerosis alone exceeds
the working budget from section 2. Taken together the eight overlap heavily and still
come to 2,745,052 induced triples at two hops, against 21,477 at one hop. There is no
hop radius that lands a handful of diseases in the middle of the budget: the step from
one to two hops is a factor of a hundred.

That is the opposite of what the incident counts suggested, and the error was mine —
I measured reach and reasoned about content. The incident column is kept in the table
because the hub and predicate-cut measurements below were computed on it.

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

Those savings are measured on incident counts, so read them as proportions rather
than as corpus sizes. The proportions are what the argument rests on, and they say
hub surgery is not a size lever worth reaching for first.

The frequency data underneath makes the same point from the other side. Across all
29,868 diseases, 11,589 distinct phenotypes are in use and the median one annotates
four diseases, while the most common — Global developmental delay at 2,255 diseases,
Seizure at 2,161, Intellectual disability at 2,107 — reach seven percent of them.
Seven percent is exactly the kind of term a sparse retriever discounts for free
through inverse document frequency, without anyone deciding it should. Dense
embedding retrieval has no such mechanism: a near-universal phenotype contributes to
a disease's vector as much as a discriminative one does. That is a real reason such
terms might hurt, and it is answerable against v1's gold set rather than by argument.

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

These are incident counts, and by the argument above that means they measure reach,
not corpus size. Read as reach, the shape is clear: the median disease touches four
neighbours, 99.4% stay under 100,000 two-hop edge ends, and the largest in all of
MONDO is 202,295. Read as a corpus budget they would be badly misleading — the
eight-disease table shows induced counts running four to seven times higher, which
puts several single diseases over the ceiling rather than a tenth of the way to it.
Recomputing the full distribution as induced counts is the obvious follow-up and has
not been done.

What the distribution does settle is that seed count, not hop radius, is the knob
with a usable range. Hop radius has two settings and they differ by a factor of a
hundred. Seed count is continuous, and because neighbourhoods overlap heavily it
grows sublinearly — the eight-disease union at two hops is 2,745,052 induced triples
against the 8.3M its rows sum to, a discount of about two thirds.

The distribution also indicts the sample above. The median disease has four
neighbours and 420 two-hop edges. All eight chosen by hand sit far into the tail,
because well-studied diseases are what comes to mind when picking examples. That
skew matters most for the whole-graph option: a 1.46M-node corpus is dominated by
sparsely annotated terms whose text is little more than a label, and how retrieval
behaves over a corpus of mostly-bare documents is a quality question that no amount
of runtime measurement will answer.

### Measured: closure, and the subset that fits

If a handful of diseases is too small at one hop and over budget at two, the next
instinct is to stop choosing a radius and take the closure — everything reachable
from the seeds. Growing the EDS neighbourhood hop by hop until it stops growing takes
four seconds:

| hop | nodes | new | induced edges | % of graph nodes |
|---|---|---|---|---|
| 1 | 832 | 832 | 4,564 | 0.1% |
| 2 | 33,310 | 32,478 | 978,579 | 2.3% |
| 3 | 474,718 | 441,408 | 11,608,169 | 32.5% |
| 4 | 894,713 | 419,995 | 14,814,020 | 61.2% |
| 5 | 1,007,053 | 112,340 | 15,144,560 | 68.9% |
| 6 | 1,022,202 | 15,149 | 15,183,648 | 69.9% |
| 12 | 1,028,033 | 44 | 15,194,439 | 70.3% |

By hop three it holds 76% of the graph's edges, and it converges on a component of
about 1.03M nodes carrying 99.9% of them. Closure is not a knob at all, and not
because it is merely large: reachability closure is a connected-component property,
so every disease in that component has the identical closure. The closure of one
disease and the closure of a hundred are the same object. Only diseases stranded in
small isolated components would differ, which is a separate question worth asking but
not a way to size a subset.

What does land inside the budget is dropping the seed choice entirely and keeping the
radius at one: every disease, one hop out.

```
all 29,868 diseases, one hop:  89,051 nodes   1,094,548 induced triples
```

That is the first subset that fits without a seed choice to defend. It inherits none
of the name-match artefacts, and at roughly 1.1M triples over 89k nodes it is dense
enough to give retrieval something to work with. But it is still a boundary drawn
where the machine runs out, which the next two subsections take apart. It is made of 29,868 diseases,
17,259 variants, 11,557 phenotypes, 9,573 cases, 8,741 genotypes and 6,207 genes,
joined mostly by `has_phenotype`, `subclass_of`, `causes` and the treatment
predicates.

Its boundary is the gene side. Only 6,207 genes get in, and no gene-gene or
gene-phenotype edge that does not pass through a disease. Questions reasoning outward
from a gene or a phenotype hit that edge of the world, and what it would cost to
extend the subgraph among the genes already present has not been measured.

### Three kinds of boundary, and what closure actually contains

Every subset above was drawn by distance or by capacity, and both are arbitrary with
respect to the question being asked. There is a third option — draw the boundary by
relevance, from what the use cases need — and it is the only one that can be argued
without reference to hardware. Taking closure first is a way of refusing the capacity
boundary, which is right. But closure does not supply a relevance boundary; it
supplies no boundary at all, and then the graph's construction accidents become the
boundary instead.

What "everything about a disease" contains, measured:

| axis | share |
|---|---|
| edges touching a non-human species | 67.6% |
| nodes that are mouse | 24.9% |
| nodes that are zebrafish | 11.8% |
| nodes that are human | 3.8% |
| `interacts_with` edges | 18.1% |
| `expressed_in` edges | 16.1% |
| `has_phenotype` edges | 14.5% |
| `orthologous_to` edges | 11.4% |
| largest single source (MGI, mouse genome database) | 15.5% |

So the closure of Ehlers-Danlos is not everything about Ehlers-Danlos. It is
Ehlers-Danlos plus the entire model-organism molecular substrate, reached through
gene interaction and orthology edges. Three hops out you are reading zebrafish
expression data. The completeness is real but it is completeness with respect to what
Monarch merged, not with respect to the disease.

There is also no operation in a text-embedding pipeline that uses a closure. Retrieval
embeds the query into a vector and takes the nearest documents; the graph decides
only which documents exist. Reachability would matter for multi-hop graph reasoning —
v1's second sub-project — but not here.

### Paring back by relevance

Applying cuts that can each be defended from v2's use cases — human phenotyping,
cohort discovery, drug repurposing — with capacity given no vote until the end:

| relevance cut | nodes | triples | diseases kept |
|---|---|---|---|
| whole graph (= closure) | 1,047,586 | 15,211,571 | 29,866 (100%) |
| drop edges touching a non-human species | 442,307 | 4,923,997 | 29,866 (100%) |
| + drop molecular infrastructure predicates | 398,627 | 1,845,318 | 29,866 (100%) |
| + drop variant and genotype nodes | 381,237 | 1,800,380 | 29,866 (100%) |

Disease coverage never moves: all 29,866 survive every cut. The species cut alone
removes two thirds of the graph and costs nothing a human-phenotyping question would
have used.

One constraint governs which of these cuts are legitimate, and it comes from what the
subset is for. This graph has to outlast the current question — the point of the line
is to compare retrieval methods, text embedding against graph traversal against
network embedding, on the *same* substrate. A cut tuned to the method being measured
would rig the comparison.

By that test the cuts are not equal. Dropping non-human species is method-neutral:
no method under comparison is trying to answer with zebrafish data. Dropping
molecular infrastructure is not — `interacts_with` is precisely the structure a
network embedding would exploit for drug repurposing, and removing it because a text
retriever has no use for it decides the experiment in advance. Dropping variant and
genotype nodes is the same kind of judgement, made because their text is largely
identifiers, and it saves only 45k triples because most such nodes were non-human and
already gone.

Which leaves an honest tension rather than a clean answer. The method-neutral
boundary — human, everything else kept — is 442,307 nodes and 4,923,997 triples.
As a node corpus that is comfortable. As a triple corpus it is roughly 15 GB of
vectors at 768 dimensions, and it does not fit. Capacity comes back, but now as a
named conflict between a defensible graph and this machine, which is exactly the
kind of measured wall section 5 is looking for — rather than as the thing that
silently chose the graph in the first place.

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
