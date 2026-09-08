Yes. **Now that I can see your actual `toc_v2.py`, I would change my earlier assessment of `hybrid_search_hierarchical.py`.** The TOC generator gives you a much better, explicit mapping mechanism than the hybrid search is currently using.

Your `toc_v2.py` establishes this important contract:

```text
TOC node
 ├── toc_id
 ├── block_id
 ├── heading_path
 └── children
```

and, crucially:

```text
block_id_to_toc_id
heading_path_to_toc_id
```

So the hybrid search **should use the TOC structure rather than trying to infer hierarchy from the `toc_id` string**.

## The main issues in hybrid search

### 🔴 1. `startswith(chosen + ".")` should be removed

The current hybrid search apparently does something equivalent to:

```python
row["toc_id"] == chosen or row["toc_id"].startswith(chosen + ".")
```

Your `toc.py` already knows the actual hierarchy:

```text
S6
├── S6.1
│   ├── S6.1.1
│   └── S6.1.2
└── S6.2
```

Therefore, don't derive parent/child relationships from:

```text
"S6.1.2".startswith("S6.1.")
```

Instead:

```text
Router selects S6.1
       ↓
TOC tree finds S6.1
       ↓
collect descendants
       ↓
[S6.1, S6.1.1, S6.1.2]
       ↓
retrieve those chunks
```

This is much more robust for other Cigna PDFs.

---

# 🔴 2. The fallback to ALL chunks is wrong

This is the bigger problem:

```python
if not candidate_indices:
    candidate_indices = list(range(num_chunks))
```

Given your architecture, this should **not happen**.

Imagine:

```text
Router:
document = Cigna_X
toc_ids = ["S7.2"]
```

Then:

```text
TOC resolver
     ↓
S7.2 exists
     ↓
metadata has no chunks for S7.2
```

The current implementation says:

```text
No candidates
     ↓
search entire document
```

That defeats the purpose of your TOC routing.

It should instead be:

```text
No candidates
     ↓
No scoped content found
     ↓
return no results
```

Then your synthesis layer can know:

> The routed section does not contain retrievable content.

---

# 🔴 3. `search(query)` is incorrectly using the query as `policy_hint`

You currently have the issue where:

```python
search(query)
```

eventually does:

```python
load_index(policy_hint=query)
```

That's not compatible with your new architecture.

The policy has already been determined by Stage 2.

It should be:

```text
User query
    ↓
TOC Router
    ↓
document_key = Cigna_ACDF
toc_ids = [...]
    ↓
hybrid_search(
    query,
    policy_hint="Cigna_ACDF",
    candidate_toc_ids=[...]
)
```

The hybrid search should **never try to figure out which policy the user means**.

That's the router's job.

---

# 🔴 4. Your `toc.py` gives you a better mapping than the current metadata matching

This is particularly important.

Your TOC produces:

```json
{
  "block_id_to_toc_id": {
    "b123": "S7",
    "b124": "S7.1",
    "b125": "S7.1.1"
  }
}
```

and:

```json
{
  "heading_path_to_toc_id": {
    "CMM-601 > General Guidelines": "S7.1"
  }
}
```

This means your pipeline has **two legitimate join strategies**:

### Best

```text
chunk → source block_id → toc_id
```

### Fallback

```text
chunk → heading_path → toc_id
```

You should prefer the first.

---

# 🔴 5. Your chunk metadata needs a canonical `toc_id`

The entire system becomes much simpler if your embedding metadata contains:

```json
{
  "chunk_id": "chunk_123",
  "toc_id": "S7.1.2",
  "heading_path": [
    "CMM-601",
    "General Guidelines",
    "Application of Guideline"
  ],
  "text": "..."
}
```

Then retrieval becomes trivial:

```python
allowed_toc_ids = {"S7.1", "S7.1.1", "S7.1.2"}

candidate_indices = [
    i for i, row in enumerate(metadata)
    if row["toc_id"] in allowed_toc_ids
]
```

No guessing.

No ACDF-specific rules.

No parsing `S7.1.2`.

---

# 🟡 6. `toc.py` itself still generates `S1`, `S1.1`, etc.

This is technically a convention:

```python
toc_id = f"S{i}" ...
```

But **I would NOT change this.**

It's not PDF-specific.

You're defining your own internal identifier namespace.

For example:

```text
Cigna_ACDF:
S1
S1.1
S1.2

Cigna_Lab:
S1
S1.1
S1.2
```

That's perfectly fine because the `toc_id` is scoped by:

```text
document_key + toc_id
```

So:

```text
(Cigna_ACDF, S7.1)
```

and:

```text
(Cigna_Lab, S7.1)
```

are different nodes.

The problem isn't the `S7.1` format.

The problem would be **code assuming the format represents hierarchy**.

---

# 🟢 7. Your `toc.py` hierarchy is actually exactly what we need

This is good:

```python
while stack and stack[-1][0] >= level:
    stack.pop()
```

and:

```python
parent["children"].append(node)
```

You have a real tree.

Then:

```python
collect_all_content(node)
```

also gives you the complete subtree content.

So your TOC JSON can act as the **authoritative routing structure**.

That's the design I'd use.

---

# One concern in `toc.py`

There is one thing I want you to be aware of.

You call:

```python
prune_matching_subtrees(toc_tree, FLATTEN_SECTION_KEYWORDS)
```

with:

```python
FLATTEN_SECTION_KEYWORDS = ["reference"]
```

So a heading such as:

```text
References
```

will have:

```json
"children": []
```

even though its children existed originally.

That's intentional according to your comment.

But it means your final TOC hierarchy isn't necessarily the **true document hierarchy**.

If the router ever needs to distinguish sections under References, it won't be able to.

For clinical retrieval this may be perfectly reasonable, but I would make this a configurable preprocessing decision rather than something the retrieval layer knows about.

---

# Your ideal mapping should now be this

I think this is the cleanest architecture for what you're building:

```text
                 DOCLOING JSON
                      │
                      ▼
                   toc.py
                      │
          ┌───────────┴────────────┐
          ▼                        ▼
      toc_tree                lookup tables
          │                 block_id → toc_id
          │                 heading → toc_id
          │
          ▼
     TOC JSON
          │
          │
          ├─────────────────────────────┐
          │                             │
          ▼                             ▼
     Router LLM                    Chunking
          │                             │
          │                             ▼
          │                       chunk metadata
          │                             │
          │                             ▼
          │                         toc_id
          │                             │
          └──────────────┬──────────────┘
                         ▼
                  SCOPED RETRIEVAL
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
           Dense                  BM25
              │                     │
              └──────────┬──────────┘
                         ▼
                       RRF
                         │
                         ▼
                    Top chunks
                         │
                         ▼
                        LLM
```

## And BM25's exact role is now clear

BM25 does **not** participate in TOC mapping.

The order is:

```text
1. TOC determines WHERE to search
2. BM25 determines WHICH text matches
3. Dense determines WHICH text is semantically similar
4. Fusion combines them
5. LLM interprets the retrieved policy
```

So:

```text
TOC = scope
BM25 = lexical relevance
Dense = semantic relevance
LLM = reasoning/synthesis
```

That's the clean separation.

---

# What I would change in `hybrid_search_hierarchical.py`

### Remove

```text
❌ query → policy selection
❌ toc_id.startswith(...)
❌ no-candidate → entire document
❌ assumptions that IDs encode hierarchy
```

### Keep

```text
✅ per-policy metadata
✅ per-policy embeddings
✅ per-policy BM25
✅ dense search
✅ BM25 search
✅ hybrid scoring
✅ sibling/context expansion, with some refinement
```

### Add/use

```text
✅ TOC tree as authoritative hierarchy
✅ document_key + toc_id as scope
✅ explicit descendant resolution
✅ block_id → toc_id mapping
✅ strict empty-scope behavior
```

---

## One important thing remains

I **don't want to modify the hybrid search yet**, because we need to see how your chunks were actually generated.

The key question is:

> **Does your metadata JSON contain the original `block_id` or only the heading/section information?**

If it has `block_id`, we can make the mapping extremely reliable:

```text
Docling block
     ↓
toc.py
     ↓
block_id → toc_id
     ↓
chunk metadata
     ↓
toc_id
```

If it doesn't, we'll use your `heading_path_to_toc_id` mapping, but we'll need to check for duplicate heading paths.

### Send me these next:

1. **`cpt_table_lookup.py`**
2. **`policies_manifest.json`**
3. **A sample of your generated metadata JSON** — ideally 10–20 records including different hierarchy levels.

The **metadata JSON is the most important next file**. Once I see it, I can tell you exactly how `TOC → chunks → BM25/embeddings` should be wired without making assumptions.
