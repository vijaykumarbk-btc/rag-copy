Yes — the overall direction is correct, but I would make **one important architectural adjustment** before you continue.

## My assessment

Your pipeline should now become:

```text
PDF
 ↓
Docling / hierarchical processing
 ↓
Cigna_ACDF_hierarchical.md
 ↓
toc_v2.py
 ↓
ACDF_toc_output_new.json
 ├── TOC tree
 ├── flat_toc
 ├── toc_id
 ├── heading_path
 └── lookup mappings
        ↓
   CHUNKING + TOC MAPPING
        ↓
 enriched_chunks.json
        ↓
 CONTEXTUAL EMBEDDING
        ↓
 embeddings.npy + metadata.json
        ↓
 BM25 index
        ↓
 TOC-FIRST RETRIEVAL
        ↓
 scoped hybrid retrieval
        ↓
 LLM
```

The key point is:

> **The Markdown remains your content source, while the TOC JSON becomes your structural authority.**

I would **not immediately replace your Markdown chunker with direct chunking from `flat_toc`** unless you have confirmed that `flat_toc` contains every piece of content exactly once and preserves tables/content correctly.

Since you said your current chunking results are already good, preserve that logic.

---

# Step 1 — Keep your existing chunking logic

Your current `chunking_heirarchical.py` is already producing good chunks.

So don't redesign chunking.

The change should be:

```text
Current chunk
      +
TOC metadata
      =
Enriched chunk
```

For example, currently:

```json
{
  "chunk_id": 42,
  "source": "Cigna_ACDF_hierarchical.md",
  "section": "CMM-601 > Initial Primary ACDF > Radiculopathy",
  "parent_section": "CMM-601",
  "subsection": "Radiculopathy",
  "section_type": "criteria",
  "chunk_type": "text",
  "text": "..."
}
```

Should become:

```json
{
  "chunk_id": 42,

  "source": "Cigna_ACDF_hierarchical.md",

  "toc_id": "S9.1.1",

  "docling_section_id": "s0004",

  "heading_path": [
    "CMM-601: Anterior Cervical Discectomy and Fusion",
    "Initial Primary Anterior Cervical Discectomy and Fusion (ACDF)",
    "Radiculopathy"
  ],

  "section": "CMM-601: Anterior Cervical Discectomy and Fusion > Initial Primary Anterior Cervical Discectomy and Fusion (ACDF) > Radiculopathy",

  "parent_section": "Initial Primary Anterior Cervical Discectomy and Fusion (ACDF)",

  "subsection": "Radiculopathy",

  "section_type": "criteria",

  "chunk_type": "text",

  "text": "..."
}
```

---

# Step 2 — Map chunks to the TOC

This is the most important next implementation.

Your TOC JSON should **not replace chunking**.

Instead:

```text
chunk
 ↓
extract heading hierarchy
 ↓
normalize heading path
 ↓
match against TOC heading_path
 ↓
assign toc_id
```

Conceptually:

```text
Chunk:

CMM-601
 └── Initial Primary ACDF
      └── Radiculopathy


TOC:

S9
 └── S9.1
      └── S9.1.1
```

Result:

```text
chunk.toc_id = S9.1.1
```

---

# Step 3 — Use exact path matching, not subsection matching

This is critical.

Do **not** do:

```python
if subsection == "Radiculopathy":
```

because `"Radiculopathy"` appears in multiple locations.

Instead match:

```text
Full heading path
```

For example:

```text
CMM-601
>
Initial Primary Anterior Cervical Discectomy and Fusion (ACDF)
>
Radiculopathy
```

against:

```json
"heading_path": [
  "CMM-601: Anterior Cervical Discectomy and Fusion",
  "Initial Primary Anterior Cervical Discectomy and Fusion (ACDF)",
  "Radiculopathy"
]
```

This resolves ambiguity.

---

# Step 4 — Create a dedicated mapping stage

I recommend separating this from chunking.

Instead of modifying everything inside:

```text
chunking_heirarchical.py
```

your pipeline should ideally become:

```text
chunking_heirarchical.py
        ↓
raw_chunks.json
        ↓
chunk_toc_mapper.py
        ↓
enriched_chunks.json
        ↓
embedding_with_section.py
```

Why?

Because these are logically different responsibilities.

### Chunker

Responsible for:

```text
Markdown
→ headings
→ tables
→ criteria
→ chunk boundaries
```

### TOC mapper

Responsible for:

```text
Chunk heading path
→ TOC lookup
→ toc_id
→ hierarchy metadata
```

### Embedder

Responsible for:

```text
Enriched chunk
→ contextual embedding text
→ vector
```

This will make debugging much easier.

---

# Step 5 — Add mapping validation

Do not silently allow missing `toc_id`.

After mapping, generate statistics like:

```text
Total chunks:          250
Mapped chunks:         247
Unmapped chunks:       3
Mapping rate:          98.8%
```

For unmapped chunks print:

```text
Chunk ID: 73

Heading path:
CMM-601
>
General Guidelines
>
Health Equity Considerations
```

This is important because it will reveal:

* heading normalization issues
* Markdown hierarchy issues
* TOC generation issues
* sections not captured by TOC

Ideally:

```text
100% of meaningful chunks
```

should map to a `toc_id`.

Some document boilerplate may intentionally map to a document-level/root ID.

---

# Step 6 — Preserve the chunk's own order

Add a field such as:

```json
"chunk_index": 42
```

or keep `chunk_id` strictly sequential.

This becomes useful later.

For example:

```text
S9.1.1
 ├── chunk 41
 ├── chunk 42
 ├── chunk 43
 └── chunk 44
```

If retrieval hits chunk 43, you can reconstruct:

```text
chunk 41
chunk 42
chunk 43 ← direct hit
chunk 44
```

This is exactly what you wanted earlier with section expansion.

---

# Step 7 — Embedding strategy

Your current embedding approach is conceptually correct.

I recommend embedding:

```text
Document context
+
TOC hierarchy
+
actual chunk content
```

Conceptually:

```text
Cigna ACDF Medical Coverage Policy

Section:
CMM-601: Anterior Cervical Discectomy and Fusion
> Initial Primary Anterior Cervical Discectomy and Fusion (ACDF)
> Radiculopathy

Section ID: S9.1.1

Content:
...
```

### Important point about `toc_id`

The ID itself:

```text
S9.1.1
```

has little semantic meaning to an embedding model.

So don't rely on the ID for semantic retrieval.

The valuable embedding context is:

```text
Initial Primary ACDF > Radiculopathy
```

The `toc_id` is primarily for:

* filtering
* grouping
* hierarchy expansion
* auditing
* retrieval control

So:

```text
heading_path → semantic context
toc_id       → structural identity
```

This distinction is important.

---

# Step 8 — Save embeddings separately from metadata

Your output should look like:

```text
data/
│
├── chunks/
│   └── Cigna_ACDF_enriched_chunks.json
│
├── embeddings/
│   └── Cigna_ACDF_embeddings.npy
│
├── metadata/
│   └── Cigna_ACDF_metadata.json
│
└── bm25/
    └── Cigna_ACDF_bm25.pkl
```

Metadata should contain:

```json
{
  "chunk_id": 42,

  "toc_id": "S9.1.1",

  "docling_section_id": "s0004",

  "heading_path": [...],

  "section": "...",

  "chunk_index": 42,

  "chunk_type": "criteria",

  "section_type": "criteria",

  "text": "..."
}
```

The embedding row index must correspond exactly to metadata index.

For example:

```text
embeddings[42]
        ↓
metadata[42]
        ↓
chunk 42
```

This invariant must never break.

---

# Step 9 — Build a TOC index separately

You now have enough information to build two indexes.

## Index A — Content retrieval

```text
Chunks
+
Dense embeddings
+
BM25
```

Used to find:

```text
exact evidence
```

## Index B — TOC navigation

```text
TOC nodes
+
heading text
+
toc_id
+
parent/children relationships
```

Used to answer:

```text
Which part of the document should I search?
```

This supports your intended architecture.

---

# Step 10 — Your intended retrieval architecture

This should be the next major phase.

## Query

```text
What are the criteria for repeat ACDF due to pseudoarthrosis?
```

---

## Phase A — TOC selection

Give the LLM or TOC retrieval layer:

```text
S9  Initial Primary ACDF
S10 Anterior Cervical Corpectomy
S11 Repeat ACDF
   S11.1 ...
   S11.1.3 Radiculopathy with Pseudoarthrosis
S12 Adjacent Segment Disease
S13 Failed Disc Arthroplasty
```

Identify:

```text
S11
or
S11.1.3
```

---

## Phase B — Scoped retrieval

Instead of searching all chunks:

```text
250 chunks
```

search only:

```text
chunks belonging to S11
```

or:

```text
S11.*
```

Then run:

```text
Dense search
+
BM25
```

This is where your existing hybrid retrieval becomes more powerful.

---

## Phase C — Expand section

Suppose BM25 retrieves:

```text
Chunk 83
toc_id = S11.1.3
```

Retrieve:

```text
all chunks belonging to S11.1.3
```

ordered by:

```text
chunk_id
```

Then send the complete section to the LLM.

---

# Recommended final architecture

I would structure the project like this:

```text
PDF
 │
 ▼
Docling
 │
 ▼
Cigna_ACDF_hierarchical.md
 │
 ├─────────────────────┐
 ▼                     ▼
Chunking               TOC generation
 │                     │
 ▼                     ▼
raw_chunks.json        ACDF_toc_output_new.json
 │                     │
 └──────────┬──────────┘
            ▼
       TOC mapping
            │
            ▼
   enriched_chunks.json
            │
       ┌────┴────┐
       ▼         ▼
 Embeddings     BM25
       │         │
       └────┬────┘
            ▼
       Hybrid Search
            ▲
            │
      TOC-first filter
            │
            ▼
        TOC tree
```

---

# Issues I would watch for

## 1. Don't embed the numeric ID as if it creates semantic meaning

Good:

```text
Initial Primary ACDF > Radiculopathy
```

Less useful semantically:

```text
S9.1.1
```

Keep both, but understand their different purposes.

---

## 2. Heading normalization must be deterministic

Your Markdown and TOC may differ because of:

```text
ACDF
```

versus:

```text
Anterior Cervical Discectomy and Fusion (ACDF)
```

or:

```text
CMM-601.4:
```

versus:

```text
CMM-601.4
```

You need one shared normalization strategy before matching.

For example, normalize:

* whitespace
* Markdown symbols
* numbering punctuation
* repeated spaces
* case if appropriate

But **do not aggressively remove meaningful words**.

---

## 3. Don't map by heading text alone

This would fail:

```text
Radiculopathy
```

because duplicate headings exist.

Always prefer:

```text
full heading_path
```

---

## 4. Decide what happens with parent-level content

Suppose:

```text
S9
Initial Primary ACDF
```

has introductory content before:

```text
S9.1 Radiculopathy
```

That introductory content should map to:

```text
S9
```

not be artificially assigned to `S9.1`.

This is important for correct hierarchy retrieval.

---

## 5. Keep `toc_id` immutable

Once:

```text
chunk_id 42 → S9.1.1
```

is assigned, all downstream systems should preserve it unchanged.

Do not regenerate IDs during embedding or retrieval.

---

# My recommended next implementation order

### Phase 1 — TOC validation

* Validate `toc_tree.txt`
* Check duplicate heading paths
* Check parent-child relationships
* Confirm all meaningful sections have IDs

### Phase 2 — Chunk ↔ TOC mapping

* Keep current chunker
* Create dedicated mapping stage
* Add `toc_id`
* Add `docling_section_id`
* Add canonical `heading_path`

### Phase 3 — Mapping audit

Produce:

```text
total chunks
mapped chunks
unmapped chunks
duplicate mappings
mapping percentage
```

This should be completed before embedding.

### Phase 4 — Embedding update

Modify contextual embedding text to include:

```text
heading_path
+
chunk text
```

Keep `toc_id` in metadata.

### Phase 5 — Rebuild BM25

BM25 should index either:

```text
heading context + text# RAG Pipeline — Setup & Next Steps

## Context

This project builds a section-aware RAG pipeline over Cigna medical policy
PDFs (e.g. `Cigna_ACDF.pdf`, `Cigna_Lumbar_Fusion.pdf`). The pipeline has
four stages already working, a fifth stage (retrieval) still to be built.

**The core idea:** every document gets a Table of Contents with stable
section IDs (`S1`, `S1.1`, `S1.1.2`, ...). Every chunk that gets embedded
is tagged with the `toc_id` of the section it came from. At query time, an
LLM first picks which `toc_id`(s) are relevant from the TOC alone (cheap,
no chunk content needed), retrieval is then scoped to just those chunks,
and a hybrid of BM25 + embedding similarity picks the final top-k chunks
to send to the answering LLM.

```
PDF
 │  (1) Docling parse + hierarchy postprocessor
 ▼
hierarchical.json  +  hierarchical.md
 │                        │
 │ (2) toc.py              │ (3) chunker
 ▼                        ▼
toc_output.json        chunks.json
        \                 /
         \  (4) embed_chunks.py
          \      (joins chunks -> toc_id via heading path)
           ▼
   embeddings.npy  +  metadata.json  (chunk text + toc_id, aligned by row index)
           │
           │ (5) retrieve.py  <-- NOT YET BUILT, see spec below
           ▼
   TOC-routed, hybrid-retrieved chunks -> answering LLM
```

## Directory layout (adjust paths below if yours differ)

```
project2/
├── data/raw/                                  # source PDFs
├── output/                                    # Docling stage output (step 1)
│   ├── Cigna_ACDF_hierarchical.json
│   └── Cigna_ACDF_hierarchical.md
├── hierarchical-processing/
│   └── md/
│       ├── <doc>_hierarchical.md               # copied/symlinked from output/
│       ├── <doc>_toc_output.json                # step 2 output
│       ├── toc_tree.txt                         # step 2 output (human-readable)
│       ├── chunks/
│       │   └── <doc>_hierarchical_chunks.json   # step 3 output
│       └── embeddings/
│           ├── <doc>_embeddings.npy             # step 4 output
│           └── <doc>_metadata.json              # step 4 output
└── retrieve.py                                  # step 5 -- to build
```

## Step-by-step

### Step 1 — Docling parse (no changes needed)

Existing script. Produces `<doc>_hierarchical.json` (blocks with
`block_id`, `heading_level`, `reading_order`, `heading_path`, etc.) and
`<doc>_hierarchical.md`.

Run once per PDF, for both `Cigna_ACDF.pdf` and `Cigna_Lumbar_Fusion.pdf`.

### Step 2 — Build the TOC (`toc.py`) — **updated, replace existing file**

Use the version attached to this doc (`extract_toc.py` in this
conversation's outputs — rename to `toc.py` in the repo, overwriting the
old one). Changes vs. the old version:

- Prunes the References section subtree (heading still listed, nothing
  nested under it) — old version had runaway nesting there.
- Adds `toc_id` to every heading (`S1`, `S1.1`, `S1.1.2`, ...), generated
  purely from tree position — doesn't depend on Docling's own
  `section_id`, which is unreliable/missing.
- Adds two lookup tables to the output JSON, used for joining against
  chunks/embeddings later:
  - `block_id_to_toc_id` — exact join key if a chunk ever carries
    `block_id`.
  - `heading_path_to_toc_id` — join key when a chunk only carries a
    heading breadcrumb string (this is the current situation — see
    Step 4).

Edit the three paths at the top of the file (`INPUT_JSON_PATH`,
`OUTPUT_JSON_PATH`, `OUTPUT_TREE_TXT_PATH`) and run for each document.

**Verify:** open `toc_tree.txt` and confirm the References section shows
no children, and every heading has a `[Sx.y]`-style tag.

### Step 3 — Chunk the Markdown (no changes needed)

Existing script. Produces `<doc>_hierarchical_chunks.json`. Each chunk
record has `section`, `parent_section`, `subsection` (heading breadcrumb
strings) but **no `block_id`** — this is why Step 2 also builds the
`heading_path_to_toc_id` lookup, to bridge the gap.

### Step 4 — Embed chunks (`embed_chunks.py`) — **updated, replace existing file**

Use the version attached to this doc. Changes vs. the old version:

- Loads the TOC output JSON from Step 2 (new `TOC_FILE` path — set this
  at the top of the file, one per document).
- Before embedding each chunk, resolves `toc_id` via `find_toc_id()`
  (exact heading-path match, with two fallback strategies) and attaches
  `toc_id` + `toc_match_method` to the chunk as metadata.
- `toc_id` is **not** included in the text sent to the embedding model
  (an arbitrary code has no semantic content) — only the existing
  heading-title context + chunk text is embedded, same as before.
- Metadata rows stay in the same order/count as the input chunks list —
  this must be preserved, since `metadata.json` row *i* is positionally
  aligned with `embeddings.npy` row *i*.

Edit `CHUNKS_FILE`, `TOC_FILE`, `EMBEDDINGS_FILE`, `METADATA_FILE` at the
top, then run per document.

**Verify:** the console prints a match summary at the end, e.g.:
```
TOC mapping summary:
  exact_path          312 (96.0%)
  subsection_suffix     9 (2.8%)
  parent_only           2 (0.6%)
  UNMATCHED              1 (0.3%)
```
This should be close to 100% `exact_path`. If not, the printed
`UNMATCHED` examples show the offending `section` strings — investigate
whether the Markdown heading text differs from the Docling JSON heading
text (whitespace, smart quotes, `#`-level drift from the hierarchy
postprocessor).

### Step 5 — Build `retrieve.py` (NOT YET BUILT — implement this)

Implement a three-stage retrieval flow:

**Stage A — TOC routing (LLM call #1).**
Load `toc_output.json`, render a compact version of the TOC (title +
`toc_id` + page only — no chunk content, keep this call cheap). Prompt an
LLM: given the user's query and this TOC, return the `toc_id`(s) most
likely to contain the answer. Use the same OpenAI-compatible client
pattern already used for embeddings (`OLLAMA_HOST` / a chat model — add a
`CHAT_MODEL` env var alongside the existing `MODEL` embedding var if one
doesn't already exist). Ask for structured output (a JSON list of
`toc_id`s) so it's parseable.

**Stage B — Scope + hybrid retrieval.**
```python
candidates = [
    row for row in metadata
    if row["toc_id"] and any(
        row["toc_id"] == chosen or row["toc_id"].startswith(chosen + ".")
        for chosen in chosen_toc_ids
    )
]
```
(`startswith(chosen + ".")` so picking a parent section like `S9` also
pulls in its children `S9.1`, `S9.2`, etc.)

Run BOTH retrievers over `candidates` only:
- **BM25** (`rank_bm25` — `pip install rank_bm25`) over each candidate's
  `text` field. Good for exact terms this document is full of: CPT
  codes, `C5-C6`, `CMM-601.4`, etc., which embeddings can blur.
- **Cosine similarity** between the query embedding and each candidate's
  row in `embeddings.npy` — pull rows using the SAME index the candidate
  had in `metadata` (list order is preserved end-to-end, so
  `metadata[i]` always corresponds to `embeddings[i]`).

Fuse the two rankings with **Reciprocal Rank Fusion**:
```
score(chunk) = sum over each ranker r of  1 / (k + rank_r(chunk))
```
(`k = 60` is a common default.) Take the top-k fused results (e.g. top
5–8 chunks).

**Stage C — Final answer (LLM call #2).**
Send the top-k chunk texts (with their `section` breadcrumb as a
citation label) to the answering LLM along with the original query.

**Suggested function signature:**
```python
def retrieve(query: str, toc_data: dict, metadata: list, embeddings: np.ndarray, top_k: int = 6) -> list[dict]:
    ...
```

**Testing:** write a small script or notebook with 5-10 example
questions per document (mix of questions that need a specific
subsection, and ones that span multiple sections) and manually check
the routed `toc_id`(s) and retrieved chunks make sense before wiring up
the final-answer LLM call.

## Files provided in this conversation (attach/copy into the repo)

| File | Repo destination | Action |
|---|---|---|
| `extract_toc.py` | `hierarchical-processing/toc.py` | Replace existing |
| `embed_chunks.py` | wherever the current embedding script lives | Replace existing |
| `map_chunks_to_toc.py` | anywhere (utility script) | Optional — only needed if you ever want to re-map an *already-embedded* metadata file without recomputing embeddings (e.g. after regenerating the TOC with different IDs) |
| This file | repo root or `docs/` | Reference for Claude Code |

## Open items to confirm before/while running

- [ ] Confirm `CHAT_MODEL` (or equivalent) env var exists for the LLM
      calls in Step 5 — the existing `.env` only defines an embedding
      `MODEL`.
- [ ] Confirm both documents (`ACDF`, `Lumbar_Fusion`) have been run
      through Steps 1–4 with the *updated* scripts, not the old ones.
- [ ] Decide whether retrieval should search one document at a time or
      across a merged index of multiple documents (if multiple, add a
      `document_source` field to scope/filter on, alongside `toc_id`).
- [ ] `rank_bm25` installed (`pip install rank_bm25`).
```

or at minimum consider section titles as part of the indexed text.

### Phase 6 — Retrieval redesign

Implement:

```text
Query
 ↓
TOC candidate selection
 ↓
toc_id scope
 ↓
Hybrid retrieval
 ↓
Section expansion
 ↓
Ordered context
 ↓
LLM
```

---

## Final recommendation

**Do not change your chunking strategy right now.** Your current chunking is already working.

Your immediate next task should be:

> **Build a reliable chunk-to-TOC mapping layer between `chunking_heirarchical.py` and `embedding_with_section.py`.**

That gives you the missing structural link without risking the chunk quality you already achieved.

After that, embedding is straightforward, and then you can move to the much more important **TOC-first scoped hybrid retrieval architecture**.
