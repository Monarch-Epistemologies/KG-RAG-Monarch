# KG-RAG-Monarch — design notebook (substack draft)

Running record of *why* v2 is shaped the way it is. Written before the code.
This is an outline — sections are the questions v2 has to answer, in roughly the
order they bite. Prose to follow.

Throughout: **v1** is KG-RAG-EDS, the hand-built single-disease teaching version;
**v2** is this repo, KG-RAG-Monarch, scaling that pipeline toward the broader Monarch
graph natively on the Mac; **v3** is the not-yet-built move to Docker + RunPod, entered
only when a measured cost forces the work off this machine.

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

The relevance boundary is "keep what a human question could use, drop the rest". The
obvious way to draw it is by species: every node carries an `in_taxon_label`, so drop
any edge whose endpoint is tagged as another organism. Doing that takes the graph from
1,047,586 nodes to 442,307 and from 15.2M edges to 4,923,997, keeping all 29,866
diseases. It looked like the boundary.

It was leaky, and materializing it is what exposed the leak. A third of the surviving
442,307 nodes were model-organism phenotype and anatomy ontologies — 43,522 zebrafish
phenotype terms, 27,137 fly anatomy, 21,203 xenopus phenotype, 14,750 mouse phenotype,
and a tail of worm, yeast and slime-mould ontologies, roughly 145,000 nodes in all.
Meanwhile the Human Phenotype Ontology was 4.4% of the graph. The species filter had
missed them for a precise reason: these are ontology *classes*, not organism
instances, so they carry no taxon label, and a filter that keys on the label treats a
zebrafish phenotype term exactly as it treats a MONDO disease. The intent was "human
relevant"; the implementation was "not tagged as another organism"; the two are not
the same set.

The fix is a different kind of cut — by namespace rather than by taxon tag. An
allowlist names the namespaces a human-relevant corpus should contain: the human
clinical and genomic ones (MONDO, HP, HGNC, ClinVar, and human case data) and the
species-neutral biology that applies to human (Gene Ontology, protein, ChEBI, UBERON
anatomy, cell types, sequence and trait ontologies, Reactome pathways). An edge
survives only if both endpoints are in an allowlisted namespace. Everything else — the
whole long tail of organism-specific ontologies — is excluded by omission, so no
ever-growing blocklist has to keep pace with them.

| relevance cut | nodes | triples | diseases kept |
|---|---|---|---|
| whole graph (= closure) | 1,047,586 | 15,211,571 | 29,866 (100%) |
| drop non-human by taxon label (leaky) | 442,307 | 4,923,997 | 29,866 (100%) |
| namespace allowlist (corrected) | 299,950 | 4,097,434 | 29,866 (100%) |

Disease coverage never moves: all 29,866 survive. The corrected cut is 299,950 nodes
and 4,097,434 triples — a third of the nodes gone with barely a sixth of the edges,
because those organism ontologies were dense in internal phenotype-hierarchy edges but
sparse in links to the human disease layer.

One judgement inside the allowlist is worth naming, because it is exactly the kind of
call that should not hide. UPHENO, the unified cross-species phenotype layer, is kept.
It is species-neutral by construction and the Human Phenotype Ontology maps into it,
so by the letter of the allowlist it belongs — yet its whole purpose is to bridge to
the non-human phenotype data the cut removes. It is in for now, flagged as the first
thing to reconsider if the phenotype layer turns out noisier than the human ontologies
alone would be.

A second constraint governs which cuts are legitimate at all, and it comes from what
the subset is for. This graph has to outlast the current question — the point of the
line is to compare retrieval methods, text embedding against graph traversal against
network embedding, on the *same* substrate. A cut tuned to the method being measured
would rig the comparison. The namespace cut passes that test: no method under
comparison is trying to answer with zebrafish anatomy. A predicate cut would not —
dropping `interacts_with` because a text retriever has no use for it would remove
precisely the structure a network embedding needs for drug repurposing, deciding the
experiment in advance. So the boundary is drawn by namespace and left there;
predicates are all kept.

That leaves the method-neutral boundary at 299,950 nodes and 4,097,434 triples. The
worry was that a corpus this size does not fit as a triple corpus, and measured
against this machine the worry turns out to be smaller than it looked; section 2 works
the numbers, but the short version is that neither runtime nor memory makes the
human-relevant graph intractable. The boundary can stand on relevance, which is what
the whole detour through closure was trying to buy.

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
useful figure is documents per second on this machine. Measured on MiniLM over the
human-relevant corpus from section 1: node text runs at about 620 documents per second
and triple text at about 2,450. Triples are faster per document, not slower, because
a triple is two names and a predicate — around 47 characters — while a node carries
its synonyms and description, around 180. The counter-tenfold of triple count is
partly repaid by shorter documents.

The full numbers land nowhere near a wall. The human-relevant node corpus, 299,950
documents, embeds in about eight minutes; the human-relevant triple corpus, 4,097,434
documents, in under half an hour. Even the whole 15.2M-edge graph as triples would be a
couple of hours. This is measured at 384 dimensions; a 768-dimension biomedical model
in section 3 is slower per document and re-embeds every row from scratch, so the real
figure to hold is not one run but one run per model compared — still an overnight job
at the largest corpus, which is the patience v2 was built to spend.

The second is memory, and this is where the first draft of this section was wrong. At
384 dimensions and four bytes per float the human-relevant triple corpus is about 5.9
GiB of vectors, and the whole-graph triple corpus about 21.8 GiB. The instinct was that
21.8 GiB against 16 GB of unified memory is a hard wall. It is not, because nothing in
the retrieval path needs every full-precision vector resident at once. Storing them is
a non-issue — DuckDB keeps them on disk. Building the approximate-nearest-neighbor
index from section 4 is the step that was supposed to force residency, but ANN indexes
exist precisely to avoid it: half-precision floats halve the footprint, and product
quantization takes a 768-dimension vector down to tens of bytes, so a five-million
vector index is a few hundred megabytes with the exact vectors left on disk for
rescoring the top candidates. Five million vectors is a mid-sized index, not a large
one.

So the earlier conclusion — that triple embedding over a large graph is a capacity
wall and the clearest v3 tripwire — does not survive measurement. Memory is not the
binding constraint at these sizes. If a tripwire lives here at all it is runtime under
repeated re-embedding during model tuning, which is a patience question with a
measured rate behind it, not a wall. That reopens the human-relevant triple corpus as
a real option on this machine rather than a deferred one.

A third option is still worth naming: embed nodes, and reach facts by traversal from
retrieved entities, which is what v1 already built in its second sub-project. It buys
assertion-level answers with graph walks instead of a ten-times-larger vector index.
Whether it is a substitute for triple embedding or a weaker approximation is an
evaluation question, cheap to answer at v1 scale against the existing gold set before
committing to the larger build.

One rule governs how these corpora are built, and it is worth stating because it
looks like it violates the method-neutral cut but does not. A few nodes carry no
text at all — bare chemical entries missing their name, case reports identified only
by a UUID — and a textless node embeds to noise. Those nodes stay in the shared graph
(`nodes.tsv`/`edges.tsv`), because graph-edge traversal and network embedding can use
their structure; they are dropped only from the text corpora, which are the
text-embedding method's own input. The method-neutral rule governs the subgraph cut,
not how each method prepares its input from it — declining to feed a textless node to
the one method that needs text removes nothing from the graph the other methods see.
On the human-relevant subgraph this drops 74 nodes and 246 triples, small enough to
leave the corpus sizes essentially unchanged.

## 3. Which embedding model

The embedding model is the thing that turns each node's text into a vector, and
retrieval is only ever as good as where that model puts things. A general-purpose
model has seen ordinary web text; a biomedical model has been trained on medical and
biological language, so the question is whether that training buys placements good
enough to matter here — quality through training, not through a bigger model.

### Measuring it: synonym retrieval

The graph hands us a free test. Many nodes record their own synonyms — "myocardial
infarction" also lists "heart attack" — and the graph is thereby asserting those two
strings mean the same thing. So we can query with one held-out synonym, retrieve
against a gallery of node names, and check whether the right node comes back near the
top. The gallery holds names only, so the queried synonym is never in the text being
matched: a hit needs the model to place the two on meaning, not on shared words. That
is exactly the skill retrieval depends on, because a real question never uses the
graph's exact wording. The full instrument, and why the EDS traversal gold cannot do
this job, is written up in [`eval/`](../eval/README.md).

### The result

Two thousand synonym queries against a twenty-thousand-name gallery, the same sample
for every model so the scores are comparable. Mean reciprocal rank (MRR) scores each
query by where the right node ranked — 1 for first, ½ for second — and averages;
higher is better.

| namespace | MiniLM (general) | BioLORD | MedCPT | SapBERT |
|---|---|---|---|---|
| overall | 0.545 | 0.580 | 0.611 | **0.736** |
| HGNC (genes) | 0.19 | 0.22 | 0.26 | **0.47** |
| PR (proteins) | 0.14 | 0.16 | 0.32 | **0.46** |
| MONDO (disease) | 0.41 | 0.48 | 0.46 | **0.68** |
| CHEBI (chemicals) | 0.42 | 0.47 | 0.45 | **0.62** |
| HP (phenotype) | 0.67 | 0.84 | 0.75 | **0.89** |
| GO (gene function) | 0.70 | 0.79 | 0.79 | **0.87** |
| UBERON (anatomy) | 0.70 | 0.76 | 0.74 | **0.85** |
| OBA (attributes) | 0.86 | 0.89 | 0.91 | **0.97** |
| UPHENO (cross-species phenotype) | **0.92** | 0.80 | 0.89 | 0.91 |

The general model is the floor and it fails in a specific place: gene and protein
symbols, where a synonym is an alias like `PARK2` with no meaning on its surface to
match. That is precisely where domain training should help, and it does. SapBERT —
the one model trained directly on concept synonymy, from the UMLS medical vocabulary —
lifts genes from 0.19 to 0.47 and proteins from 0.14 to 0.46, and wins every namespace
but one without giving anything back on the descriptive vocabulary the general model
already handled. The other two biomedical models beat the baseline only modestly; the
training objective, not the fact of being biomedical, is what separates them.

One honest caveat sits under the MedCPT column. MedCPT is built as an asymmetric
query-and-document retriever, and this test runs its query encoder on both sides, which
is not its intended use — its number is a floor, not its best showing. It does not
change the ranking: SapBERT is the model, decisively, and it earns its place on the
gene and protein vocabulary that a general model cannot reach.

### Runtime cost of the choice

SapBERT is a 768-dimension model against MiniLM's 384, so its vectors are twice the
size and it is slower per document. On the built corpus that is minutes, not a wall —
the throughput measured earlier holds, and the one real recurring cost is that every
model compared means embedding the corpus again from scratch.

Retrieval quality in context — whether this model, over a given corpus, actually
answers realistic questions rather than just matching synonyms — is measured in
section 4 against a graph-derived question set, once both corpora exist.

## 4. Retrieval at scale

Before retrieval can be at scale, the vector store has to be built at scale, and
building it is where the first real hardware cost showed up — not where it was
expected.

### Building the vector store, and a lesson in where the cost isn't

The plan was unremarkable: run each node's text through SapBERT, store the resulting
768-dimension vector in a DuckDB table beside its id, and retrieve later with a single
`array_cosine_similarity` query. The whole-corpus embedding had been costed in the
which-model section at minutes, since SapBERT encodes a few hundred documents a second
on the Mac's GPU.

The first run took four hours to get halfway and was killed. The telling symptom was
that the machine looked *idle* — a few percent CPU, the GPU barely warm, the output
file crawling. That rules out the obvious suspect: if encoding were the bottleneck the
GPU would be pinned. Something downstream was starving it.

The something was the database insert. The first version bound each vector into DuckDB
row by row — a Python list of 768 floats per document, parameter-bound one at a time.
That path is roughly thirty times slower than the encoding that feeds it, so the GPU
spent almost all its time waiting for the previous batch to finish inserting. The fix
was to stop inserting row by row: encode a chunk, hand DuckDB the whole chunk as an
Arrow columnar batch (a fixed-size-list column of vectors), and let it ingest the
block in one call. Same vectors, same table — the encoding never changed — and a
3,000-document smoke test then ran at the GPU's full ~430 documents a second, which
would put the whole node corpus at about twelve minutes.

That first lesson is the one this project is built to collect: the cost of scaling is
not always where the model is. The expensive-looking part — running a 768-dimension
transformer over three hundred thousand documents — was never the problem; a mundane
data-marshalling choice was, by a factor of thirty. Profile the whole pipeline, not
the GPU.

But the twelve minutes never happened, and chasing why produced the second lesson —
one it took a wrong diagnosis to reach. With the insert fixed, the full run flew to
about a hundred thousand documents and then appeared to hang: the process sat in an
uninterruptible-looking wait, the progress log frozen for minutes at a stretch. It
looked exactly like a driver deadlock, and the first read — recorded in an earlier
draft of this section — was that Metal-backed embedding was simply unstable on this
machine. That read was wrong.

The machine is a fanless MacBook Air. Watched with `powermetrics` rather than guessed
at, the "hang" resolved into thermal throttling: under sustained load the SoC hit
*Heavy* thermal pressure and the GPU was clocked down toward its floor and, worse,
*parked* — forced idle in cooling cycles — so a chunk that took fifty seconds cool took
four to eight minutes hot, and the log sat still long enough to look dead. It never was
dead; left alone it crawled forward the whole time. The earlier "wedges" were premature
kills of a live but throttled run.

Two things sharpened this. First, `pmset` — the no-sudo thermal signal — reported
nothing, while `powermetrics` showed Heavy pressure the whole time; the coarse tool
missed it entirely. Second, and counterintuitively, throughput did not track the clock.
A chunk could flash 1100 MHz and still be slow, because what governs throughput is the
duty cycle — the fraction of time the GPU is actually executing versus parked to cool —
not its peak clock. Thermal pressure is a laggy whole-SoC flag, and the clock is a
bursty instantaneous one; neither reports the duty cycle that actually sets the rate.

The fix was physical. The laptop had a protective case on its underside, insulating the
aluminum chassis that *is* the heatsink on a fanless machine. Removing the case and
aiming a small fan at the bare metal over the SoC pulled the SoC back under its thermal
limit; the GPU boosted past 900 MHz for the first time and a chunk that had been taking
four minutes took seventy-five seconds — a four-to-sevenfold swing from cooling alone,
far more than the clock numbers suggest, because the duty cycle recovered along with the
clock. The full node corpus finished on the GPU, throttled and hand-cooled, in roughly
fifty minutes against the twelve it would take cool throughout.

That is the genuine v3-ledger entry, and it is sharper than "the GPU is unreliable": on
a fanless machine, sustained embedding is thermally bound, throughput is dominated by
heat dissipation the chassis was never designed to sustain, and a one-time build depends
on hand-managed cooling to finish in tolerable time. A machine with a fan — or a CUDA
GPU in a container — removes that entire variable. The GPU here is not unstable; it is
starved of cooling, and that starvation is a property of the hardware, not the software.

### What retrieval actually returns

With the corpus embedded, the payoff question is finally answerable: does
text-embedding retrieval surface the facts a real question needs? To measure it rather
than eyeball it, the graph supplies its own answer key. Sample a disease, template a
question about it — its symptoms, its causative gene, what treats it — and derive the
answer set by reading the edges: the phenotypes, the gene, the drugs it actually links
to. That is 180 questions across the three use-case types, each with a graph-true
answer, and no answer hand-labeled.

Scoring node-text retrieval against them — embed the question, take the twenty nearest
nodes, measure how many of the answer entities are among them — gives a two-part result
that is sharper than a single number:

| question type | answer recall | anchor recall |
|---|---|---|
| a disease's phenotypes | 0.02 | 0.97 |
| its causative gene | 0.05 | 0.92 |
| its treatments | 0.00 | 0.97 |
| overall | **0.02** | **0.95** |

The two columns say opposite things, and both matter. *Anchor recall* — does the top-k
contain the disease the question is about — is 0.95: node-text retrieval is an
excellent entity-linker, almost always finding the disease named in the question.
*Answer recall* — does it contain that disease's phenotypes, gene, or drugs — is 0.02:
it almost never surfaces the neighbours that actually answer the question. The reason
is structural, not a model weakness: the node document for "Scoliosis" is its name and
synonyms, and none of that is similar to the phrase "symptoms of Marfan syndrome". The
question and the answer live in different regions of the vector space because they
share no words.

So the measured verdict on node-text embedding is that it answers "what *is* this
disease" and not "what are this disease's neighbours" — entity lookup, not the
traversal question the use cases actually pose. That is not a dead end; it is a precise
statement of what the other two architectures are for. Graph-edge traversal starts by
finding the anchor and then walks the edges — and node-text retrieval already hands it
that anchor 95% of the time, which is exactly the front door it needs. Triple-text
embedding attacks the other side: make "Marfan syndrome has phenotype Scoliosis" a
document in its own right, and the fact becomes directly retrievable, because *that*
text does share words with the question.

And it does. Embedding the ~4M-triple corpus and scoring the same 180 questions the same
way gives the other half of the table:

| question type | node recall | triple recall |
|---|---|---|
| a disease's phenotypes | 0.02 | 0.49 |
| its causative gene | 0.05 | 0.70 |
| its treatments | 0.00 | 0.52 |
| overall | **0.02** | **0.57** |

Triple-text retrieval clears the node baseline by more than twenty-fold — 0.57 answer
recall against 0.02 — and its anchor recall is essentially perfect (0.99). This is the
nodes-vs-triples fork from section 2 settled with a number rather than an argument: for
the traversal-shaped questions the use cases actually pose, the unit you embed has to be
the fact, not the entity. The tenfold-larger corpus and its thermal cost buy a
twentyfold jump in the thing that matters. The two are not substitutes; node embedding
is a good entity-linker and a poor fact-retriever, and the reverse is roughly true of
triples — which is the empirical case for eventually running both channels together.

### From brute force to an index

Scoring exposed a second wall, this one about retrieval speed rather than quality.
Cosine over the node corpus is trivial: 300k vectors are ~0.9 GB, they fit in memory,
and all 180 questions score in one numpy matrix product in under a second. The triple
corpus does not fit — ~4M vectors are ~12 GB against 16 GB of RAM — and the first,
naive way of scoring it was to let DuckDB rank the table per question with an
`ORDER BY array_cosine_similarity ... LIMIT 20`. That is one full scan of the 12 GB
table per question, and because the table does not fit in the page cache, each of the
180 scans re-reads most of it from disk. The run was killed after eighteen minutes, I/O
bound at two percent CPU, nowhere near done — about two terabytes of reads for a
180-question eval.

The fix was to stop scanning per question. Stream the table once, and score every
question against each batch as it goes by, keeping a running top-k per question in a
heap. One pass over the 12 GB instead of 180, and the same eval finished in about five
minutes. That is a 180-to-1 reduction in I/O from a change that touches only how the
loop is nested — the same shape of lesson as the insert bottleneck earlier: at this
scale the cost lives in the data movement, not the arithmetic.

But five minutes for 180 questions is still a linear scan of the whole corpus per
query-batch, and it only looks acceptable because the eval is a one-time batch. A live
system answering one question at a time cannot re-read 12 GB per query. That is the
measured point at which brute-force cosine gives out and an approximate-nearest-neighbor
index earns its place: an index trades a one-time build and some recall for sub-linear
lookups, turning a 12 GB scan into a few hundred megabytes of resident index and a
millisecond query. Building that index, and measuring the recall it costs, is the next
open thread — and it is also where the 16 GB memory ceiling from the v3 ledger bites,
since the index wants to be resident.

## 5. Graph-edge traversal — the second retrieval method

Sections 1 through 4 measured one epistemology end to end: embed text into vectors and
retrieve by nearest-neighbour. Its verdict was two-sided — a good entity-linker (0.95
anchor recall) and, over nodes, a poor fact-retriever (0.02 answer recall) — and the
diagnosis pointed straight at the second method. If the question and its answer share
no words, stop asking a vector to bridge them. Find the node the question is *about*,
then *walk the graph* to its neighbours. The answer is not retrieved by similarity at
all; it is reached by an edge. And the thing that makes this viable is a by-product of
the first method: node-text embedding already hands us the starting node 95% of the
time. That anchor recall is the front door the crawler was waiting for.

The crawler is four steps, ported from v1's hand-built single-disease version and
re-fitted to the v2 substrate one file at a time:

- **anchor** — embed the question with SapBERT, take the nearest nodes. This is the
  0.95-recall entity-linker from section 4, reused unchanged; it must use SapBERT
  because it compares the question against the SapBERT node vectors.
- **predicate-pick** — decide which *relation* the question is asking about (symptoms?
  causative gene? treatment?) by embedding a short description of each predicate and
  ranking them against the question.
- **disambiguate** — the nearest node is often not the right one; pick the true anchor
  from the candidate pool using the graph itself.
- **traverse** — from the chosen anchor, follow the picked predicate's edges one hop and
  read off the neighbours. Pure SQL, no embedding at all.

Three of these are mechanical ports. The predicate step is where the substrate pushed
back, and it produced the section's first real finding.

### One pipeline, two different embedding models

The intuition carried over from v1 was that the crawler should use one embedding model
everywhere — the same SapBERT that won section 3 and built the node vectors. Calibration
killed that intuition. SapBERT is trained on concept term-to-term synonymy: it is
excellent at placing "heart attack" next to "myocardial infarction", which is exactly
why it won the entity-linking job. But a *question* — "What are the symptoms of Marfan
syndrome?" — is a sentence, and sentences are out of SapBERT's training distribution. Fed
the ten predicate descriptions and a question, SapBERT packs them all into a narrow
cosine band and cannot tell the right relation from the wrong ones: asked for symptoms
or for treatments, its top-ranked predicate is correct only 63% and 72% of the time.

MiniLM — the general-purpose sentence model that was the *floor* for entity linking in
section 3 — gets the same two at 100%, with wide margins between the true predicate and
the nearest distractor. The model that lost one job wins the other, because the two jobs
are different tasks: term-to-term proximity versus sentence-to-description proximity. And
the two steps are independent — the predicate classifier compares a question to
descriptions in its own private vector space and never touches the node vectors — so
there is no cost to letting each step use the model that wins it. The assembled crawler
runs SapBERT to find the entity and MiniLM to find the relation. "Pick one embedding
model" turns out to be the wrong frame; the right question is one model per step.

The same calibration retired v1's other predicate knob. v1 kept every predicate above a
fixed cosine cutoff; but a cutoff tuned for one model's cosine scale is meaningless on
another's, and the right set is really "the top predicate plus anything nearly tied with
it." So selection became a *relative* margin — keep predicates within 0.05 of the top
score — which returns exactly one predicate when there is a clear winner (a symptoms
question) and the tied cluster when there genuinely are two (genes are reached by two
predicates, treatments by two). Measured on the gold questions, that rule keeps the true
predicate 100% of the time for symptoms and treatments and 95% for genes, at fewer than
two-and-a-half predicates picked on average.

### The disambiguation that had to be rebuilt

Assembling the four steps and scoring them exposed the section's sharpest lesson: a
heuristic ported straight from v1 that, at scale, did not merely underperform but did
active harm. v1's disambiguation picked, among the anchor candidates, the one with the
most edges of the picked predicate — in a single-disease graph the disease is the unique
hub and a leaf phenotype has a handful of edges, so counting finds the disease. Ported
unchanged, that rule scored 0.37 answer recall, *worse* than triple-text embedding, and
the breakdown said why: phenotype anchor accuracy was 0.05. It was picking the wrong node
nineteen times in twenty.

The inversion is structural. At Monarch scale `has_phenotype` is one of the densest
relations in the graph, and its density is not on the disease side. A common symptom —
"Middle age onset", or "Celiac disease" appearing as a phenotypic term — is the *object*
of hundreds of has_phenotype edges, one from every disease that presents it. So "the
candidate with the most has_phenotype edges" is not the disease asked about; it is the
most common phenotype in the neighbourhood. Max-count, which found the hub in v1, now
finds the densest leaf. And it does so while discarding a correct answer: SapBERT — the
strong entity-linker v1 never had — already ranks the right disease *first* among the
candidates in most of these cases. The heuristic was overruling a front door that was
already right.

The finding generalises past the one bug: a heuristic is worth only as much as the
weakness it compensates for. v1 needed aggressive disambiguation because its MiniLM anchor
was a weak linker that often ranked a phenotype above the disease; v2's anchor is strong,
so the same aggression becomes subtraction. The fix is to trust the anchor and constrain
it only where it genuinely fails: walk the candidates in embedding-rank order and take the
first that is a disease *and* carries at least one edge of the picked predicate.

Both tests do necessary work, and cystic fibrosis shows each. Asked for its symptoms, the
nearest node by embedding is *cystic fibrosis, non-human animal*; the next disease
candidate is *breast fibrocystic disease* — near-namesakes that similarity cannot
separate. The disease-category test is not enough here: all three are MONDO diseases. What
separates them is the has-edge test — the animal stub and the fibrocystic near-miss carry
*zero* human has_phenotype edges, while the real cystic fibrosis, sitting at embedding
rank 3, carries 68. The rule walks past the empty candidates and stops at the first
disease the graph actually holds phenotypes for. No counting, no hub — just the first
plausible disease that has the facts. That single change lifted overall recall from 0.37
to 0.78.

### Traversal sidesteps the wall section 4 hit

There is a quieter payoff. Section 4 ended at a scaling wall: the triple-vector corpus is
12 GB, it does not fit in memory, and a live system cannot brute-force cosine over it per
query — hence the open thread of building an approximate-nearest-neighbour index. The
traversal step never meets that wall. It embeds nothing at query time; the one hop is an
indexed lookup over the edge table, a few hundred microseconds, and the only vectors it
touches are the ~300k node vectors the anchor step already handles comfortably. The two
methods pay their costs in different places — text-embedding retrieval pays at index-build
and query-time similarity search; traversal pays at graph-load and shifts the hard part
onto entity-linking accuracy instead.

### The result: three methods, one gold

Scored on the same 180 questions as the two text-embedding methods, the crawler produces
the third column:

| question type | node-text | triple-text | graph traversal |
|---|---|---|---|
| a disease's phenotypes | 0.02 | 0.49 | **0.89** |
| its causative gene | 0.05 | 0.70 | 0.60 |
| its treatments | 0.00 | 0.52 | **0.88** |
| overall | 0.02 | 0.57 | **0.79** |

Graph traversal wins overall, and by the widest margin exactly where text embedding
struggled most — the traversal-shaped questions this gold is made of. For a disease's
phenotypes and its treatments it clears both embedding methods decisively; the fact that
it does *not* reach 1.0 is the honest part. The walk itself is exact by construction — the
gold answers are precisely the endpoints of the edges it follows — so every point lost is
a front-door failure, an anchor mispicked or a predicate missed, not a retrieval miss. The
crawler's ceiling is its entity-linking accuracy (0.79 anchor accuracy overall), which is
why the number to improve next is the anchor, not the traversal.

Genes are the visible weak spot: 0.60 recall against triple-text's 0.70, the one cell
where embedding still wins, and gene anchor accuracy (0.65) sits well below the ~0.87 of
the other two types. Bucketing the failures says why, and the answer is mostly not a bug
to fix. Two thirds of the misses are a *near-synonym* problem: ask "what gene is
associated with Meier-Gorlin syndrome?" and the graph does not hold one Meier-Gorlin node
but several subtypes — MG1, MG2, and so on — each caused by a different gene. The question
names the family generically, the gold sampled one specific subtype, and the embedding
ranks a *sibling* subtype first; disambiguation cannot break the tie, because the sibling
is also a disease and also has a causative-gene edge. This is genuine underspecification,
not a pipeline error — the crawler returns a Meier-Gorlin gene, just not the one this gold
row happened to fix on — and only 2 of those 13 siblings even share the gold's gene, so
the phrasing really is ambiguous. The rest of the misses split between anchor-recall
gaps (the right disease not in the candidate pool at all, four cases) and a genuine bug
that *was* fixable: the predicate classifier was mis-firing on `expressed_in` for gene
questions, because that predicate's hand-written description contained the words "gene
expression" and the word "gene" pulled it toward "what gene…". Striking "gene" from that
one description recovered the affected cases. The lesson repeats section 3's: a term-list
description is data to be debugged, and one stray shared word silently mis-routes a whole
question type.

So the honest reading of the gene column is that its ceiling is entity-linking ambiguity
between disease subtypes, which a sharper anchor or a subtype-aware gold would move but a
better *walk* would not.

The larger point is the one the whole line was built to make. Three architectures, one
substrate, one answer key: embedding entities is a good entity-linker and a poor
fact-retriever; embedding facts recovers most of the ground; walking the graph, once its
front door is trusted rather than second-guessed, beats both on the questions that ask for
a disease's neighbours. None of that was arguable from first principles — each number came
from the same gold, and the ranking is the evidence for eventually running the methods
together rather than choosing one.

## 6. The v3 tripwire

The original framing had two rungs: v2 runs native on the Mac until some measured cost
makes it impractical, at which point v3 ships the work to a CUDA GPU in a container on
RunPod. Embedding the node corpus put a real number on the tripwire and, in doing so,
revealed a rung the framing skipped.

### What the thermal wall actually costs

The fanless MacBook Air cannot sustain GPU embedding at speed. Cool, SapBERT encodes
about 400 documents a second; under the Heavy thermal pressure that builds after the
first ~60,000 documents, the sustained average falls to roughly 110 — a factor of about
3.5, and up to 4x against the cold peak. The loss is not merely a lower clock: the
thermal manager parks the GPU in cooling cycles, so clock and duty cycle collapse
together and multiply. A run of cooling experiments — case off, laptop vertical in a
clamshell stand, a fan aimed dead at the bare aluminum over the SoC — moved the
throttled rate around within a band of roughly 60 to 150 documents a second but never
restored the cool ~400. External cooling nudges the ceiling; it cannot lift a fanless
chassis past the rate at which it sheds heat. For the 300k node corpus that is ~45
minutes instead of ~12; for the ~4M triple corpus it is the difference between an
afternoon and most of a day.

### The rung the framing skipped: a cooled Apple-Silicon desktop

The instinct is to read that as "the Mac era is over, go to CUDA." It is not, because
the wall is thermal, not architectural. A Mac Mini or Studio is the same Apple Silicon,
the same Metal/MPS backend, the same code — but actively cooled, so it holds full boost
under sustained load, and configurable with 24–64 GB of unified memory, which also
lifts the other native ceiling this project keeps hitting: the 16 GB limit on an in-RAM
approximate-nearest-neighbor index. One cooled box removes both walls at once, and it
does so *without* containers — which matters, because the entire reason v3 was deferred
is that Docker on Apple Silicon cannot reach the GPU. A cooled Mac keeps the native-MPS
advantage and simply adds a fan.

So the ladder has three rungs, not two:

- **v2** — the fanless laptop. Fine for building, measuring, and one-time runs that can
  be hand-cooled or left to crawl. Thermally bound on anything sustained.
- **v2.5** — a cooled Apple-Silicon desktop. Same stack, no containers, no thermal wall,
  more memory. The right answer to *this* project's measured limits.
- **v3** — Docker + a datacenter CUDA GPU on RunPod. Justified only by a need a single
  cooled desktop still cannot meet: re-embedding the full multi-million-triple corpus
  across many candidate models, where raw parallel throughput, not thermal headroom, is
  the binding constraint.

The tripwire, then, is not "leave Apple Silicon." It is "leave the *fanless* machine",
and the measured trigger is the thermal 3.5x — the point at which sustained embedding
stops being something the laptop can do patiently. The first stop past it is a cooled
Mac, and only a need for datacenter-scale parallelism justifies the jump all the way to
a CUDA container.

_(the specific workload that would clear even v2.5 — full triple-corpus re-embedding
across the model field — is named but not yet costed)_
