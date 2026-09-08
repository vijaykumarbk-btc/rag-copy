Yes. Looking at this `chunk_toc_mapper.py` together with your `toc_v2.py` and the changes you made to `hybrid_search_hierarchical.py`, I see **one major architectural issue and several smaller hardcodings/fragile fallbacks**.

The good news is: **the overall mapping strategy is right**. The mapper is close to what you need for arbitrary Cigna PDFs.

## 1. The good part: block ID is now the correct primary join

You have:

```python
block_id = chunk.get("block_id") or chunk.get("source_block_id")

if block_id and block_id in block_to_toc and block_to_toc[block_id]:
    chosen_toc_id = block_to_toc[block_id]
    match_method = "block_id_exact"
```

This is exactly the relationship we want:

```text
Docling JSON
    │
    ├── block_id
    │
    ▼
toc_v2.py
    │
    └── block_id → toc_id
                       │
                       ▼
                 chunk metadata
                       │
                       ▼
                    toc_id
```

This is much safer than matching clinical text or titles.

---

# 🔴 2. The biggest problem: `preamble_fallback` is not actually a safe mapping

You have:

```python
first_node = flat_toc[0] if flat_toc else {}
first_toc_id = first_node.get("toc_id", "S1")
```

and then:

```python
elif not sec:
    chosen_toc_id = first_toc_id
    match_method = "preamble_fallback"
```

This means:

> Any chunk without a `section` is automatically assigned to the first TOC section.

That's dangerous for a universal pipeline.

Suppose a document has:

```text
front matter
instructions
disclaimer
table
policy
```

and the first actual heading is:

```text
S1 = Instructions for Use
```

A chunk without a section might actually belong to document-level content, not S1.

Worse, if another Cigna PDF has a different structure, you're arbitrarily assigning it to the first heading.

### I would change this.

For an unmapped chunk:

```text
toc_id = null
```

rather than:

```text
toc_id = first_toc_id
```

You can still retain:

```json
"toc_match_method": "unmapped"
```

for auditing.

This is especially important because your retrieval layer now has **strict scoping**. We don't want the mapper introducing incorrect TOC associations just to achieve 100% mapping.

---

# 🔴 3. You have a hardcoded `"S1"`

This:

```python
first_toc_id = first_node.get("toc_id", "S1")
```

is technically unnecessary.

Your `toc.py` guarantees generated IDs:

```text
S1
S2
S3
...
```

but the mapper shouldn't need to know that.

Change conceptually to:

```python
first_toc_id = first_node.get("toc_id")
```

But given point #2, I'd actually remove the entire first-section fallback.

---

# 🔴 4. This is PDF/content-specific hardcoding

You have:

```python
"reference" in item.get("title", "").lower()
```

and:

```python
"reference" in sec.lower()
```

and:

```python
chunk.get("section_type") == "references"
```

and:

```python
re.match(r"^\d+\.\s+", sec)
```

The `"reference"` logic is specifically a **References-section heuristic**.

It isn't necessarily bad, but it is not universal.

More importantly, your `toc.py` already explicitly handles references:

```python
FLATTEN_SECTION_KEYWORDS = ["reference"]
```

So you now have **reference-specific logic in two separate places**:

```text
toc.py
    ↓
reference subtree pruning

chunk_toc_mapper.py
    ↓
reference fallback
```

That's unnecessary coupling.

### I'd remove the reference fallback from the mapper.

If the chunk's heading path is:

```text
References
```

then the normal heading-path mapping should handle it.

If it can't, mark it unmapped.

Don't guess.

---

# 🔴 5. This regex is especially suspicious

```python
re.match(r"^\d+\.\s+", sec)
```

This means something starting with:

```text
1. Something
2. Something
3. Something
```

gets treated as References.

That's absolutely not universal.

A Cigna policy could easily have:

```text
1. Indications
2. Contraindications
3. Documentation
```

Those are not references.

This is a genuine hardcoding/incorrect heuristic.

**Remove it.**

---

# 🟡 6. Ancestor fallback is useful, but should be audited

This part:

```python
parts = [p.strip() for p in sec.split(">")]

for k in range(len(parts) - 1, 0, -1):
    ancestor = " > ".join(parts[:k])
```

is reasonable.

For example:

```text
CMM-601 > ACDF > Indications > Radiculopathy
```

If the exact path isn't found:

```text
CMM-601 > ACDF > Indications
```

can still map the chunk to its parent.

However, there's an important consequence:

```text
exact mapping failed
      ↓
ancestor mapping
      ↓
chunk gets parent's toc_id
```

This means your mapper can produce:

```text
toc_id = S7.1
```

for a chunk that actually belongs to:

```text
S7.1.5
```

If your retrieval system then expands descendants of `S7.1`, it may retrieve more material than necessary.

That's not necessarily catastrophic, but **it reduces precision**.

I'd keep ancestor fallback as a recovery mechanism, but make it clearly visible in metadata:

```json
"toc_match_method": "ancestor_fallback"
```

which you're already doing.

Good.

---

# 🟡 7. Heading-path dictionary collision is still a potential issue

You build:

```python
norm_heading_to_toc[normalize_string(k)] = v
```

Suppose the document contains the same breadcrumb twice.

Then the later occurrence overwrites the earlier one.

For example:

```text
Policy
  General Guidelines

Another Policy
  General Guidelines
```

If their full paths differ, you're fine:

```text
Policy > General Guidelines
Another Policy > General Guidelines
```

But if your chunk `section` only contains:

```text
General Guidelines
```

then it becomes ambiguous.

This is another reason why:

```text
block_id → toc_id
```

should remain your preferred method.

---

# 🟢 8. The metadata you're producing is good

This structure is useful:

```json
{
    "chunk_id": "...",
    "chunk_index": 12,
    "source": "...",
    "toc_id": "S7.1.5",
    "toc_match_method": "block_id_exact",
    "docling_section_id": "...",
    "heading_path": [...],
    "section": "...",
    "parent_section": "...",
    "subsection": "...",
    "section_type": "...",
    "chunk_type": "...",
    "text": "..."
}
```

This gives you everything needed downstream.

I would **not remove fields** just to simplify it.

For auditing, keeping:

```text
toc_id
toc_match_method
docling_section_id
heading_path
chunk_index
```

is valuable.

---

# 🟢 9. This mapper is not ACDF-specific in the important sense

I don't see things like:

```text
CMM-601
ACDF
cervical
lumbar
radiculopathy
myelopathy
fusion
```

being used to determine mappings.

So it isn't fundamentally hardcoded to ACDF.

The actual problematic hardcodings are mostly these:

```text
❌ "reference"
❌ section_type == "references"
❌ /^\d+\.\s+/
❌ default "S1"
❌ empty section → first TOC node
```

The first three are the ones I'd remove.

---

# Recommended mapping logic

I'd simplify your mapper to this:

```text
Chunk
 │
 ├── block_id?
 │      │
 │      └── YES → block_id_to_toc_id
 │
 ├── exact heading_path?
 │      │
 │      └── YES → heading_path_to_toc_id
 │
 ├── normalized heading_path?
 │      │
 │      └── YES → normalized lookup
 │
 ├── ancestor heading_path?
 │      │
 │      └── YES → ancestor mapping
 │
 └── otherwise
        │
        ▼
      toc_id = null
```

No:

```text
"reference"
"S1"
"numbered section = references"
"first section fallback"
```

That makes it genuinely document-agnostic.

---

# One other important thing

There is a subtle distinction between **mapping** and **routing** that I think your current architecture should preserve.

Your mapper should answer only:

> **"Which TOC node does this chunk belong to?"**

It should **not** answer:

> "What should I retrieve?"

That's the job of `hybrid_search_hierarchical.py`.

So:

### `chunk_toc_mapper.py`

```text
chunk → toc_id
```

### `hybrid_search_hierarchical.py`

```text
query + document + routed toc_ids
             ↓
        allowed toc_ids
             ↓
          chunks
             ↓
       BM25 + dense
```

### `retrieval-hierarchical.py`

```text
retrieved chunks
       ↓
LLM
       ↓
clinical JSON
```

That's a very clean separation.

---

## My verdict

**Your mapper is ~80–90% of the way there.**

I would make these changes before calling it universal:

### Remove

```python
first_toc_id = first_node.get("toc_id", "S1")
```

and the entire:

```python
elif not sec:
    ...
```

fallback.

Remove:

```python
"reference" in ...
```

reference-specific fallback.

Remove:

```python
re.match(r"^\d+\.\s+", sec)
```

because that's not a valid generic indication of References.

### Keep

```text
block_id exact
exact heading path
normalized heading path
ancestor fallback
unmapped = null
match_method audit
```

And **do not change your `S1/S1.1/S1.1.1` TOC ID scheme**.

After those changes, the mapping layer will be much more genuinely reusable across Cigna policies.

The next thing I'd check is the **actual `acdf_metadata.json` and `lumbar_fusion_metadata.json` after this mapper runs**, because that will tell us whether the mapper is actually producing the correct `toc_id` distribution—not just whether the code looks correct.
