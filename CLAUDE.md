# CLAUDE.md — KG-RAG-Monarch (v2)

@../.github/CLAUDE.md

Repo-specific notes, on top of the shared line working-style imported above.

- This is **v2**: the same text-embedding pipeline scaled beyond EDS toward the
  broader Monarch graph, native on Apple Silicon. The work here is about measuring
  what scaling costs — runtime-vs-quality numbers drive the decisions.
- **Evidence before infrastructure.** Don't reach for Docker / RunPod (v3) until
  measured numbers show a step the Mac can't do patiently (see README).
