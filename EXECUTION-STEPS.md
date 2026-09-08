Viewed toc_v2.py:1-60
Viewed toc_v2.py:370-405
Viewed chunking_heirarchical.py:1-60
Viewed chunking_heirarchical.py:740-783
Viewed chunk_toc_mapper.py:1-75
Viewed chunk_toc_mapper.py:180-218
Viewed embedding_with_section.py:1-70
Viewed embedding_with_section.py:100-138
Viewed build_bm25.py:1-63

Here is the complete end-to-end pipeline with the exact `.py` files and commands needed to bring any new PDF to the exact state that **ACDF** and **Lumbar Fusion** are at today:

---

### End-to-End Pipeline Overview

```
[Raw PDF]
   │
   ▼  Step 1: docling/docling_pdf.py
[Normalized JSON + Markdown]
   │
   ├─────────────────────────────────────────┐
   ▼  Step 2: toc_v2.py                      ▼  Step 3: chunking_heirarchical.py
[TOC JSON & Text Tree]                     [Raw Markdown Chunks]
   │                                         │
   └────────────────────┬────────────────────┘
                        ▼  Step 4: chunk_toc_mapper.py
                  [Enriched Chunks JSON]
                        │
                        ▼  Step 5: embedding_with_section.py
                  [Dense Embeddings (.npy) + Metadata (.json)]
                        │
                        ▼  Step 6: build_bm25.py
                  [BM25 Lexical Index (.pkl)]
                        │
                        ▼  Step 7: Register in policies_manifest.json
                  [Ready for retrieval-hierarchical.py]
```

---

### Step-by-Step Commands:

Assume you have a new PDF named `extra_pdfs/Cigna_Knee.pdf`.

#### Step 1: Parse PDF to Hierarchical Docling JSON & Markdown
* **File**: [`docling/docling_pdf.py`](file:///home/vijaykumar/Desktop/project2/docling/docling_pdf.py)
* **What it does**: Parses the PDF with Docling, extracts bounding boxes, block IDs (`b00001`...), tables, and heading paths.
* **How to run**:
  Open `docling/docling_pdf.py` and point `PDF_PATH` to your PDF:
  ```python
  PDF_PATH = Path("extra_pdfs/Cigna_Knee.pdf").resolve()
  ```
  Then run:
  ```bash
  ./venv/bin/python docling/docling_pdf.py
  ```
* **Output**:
  - `output/Cigna_Knee_hierarchical.json`
  - `output/Cigna_Knee_hierarchical.md`

---

#### Step 2: Extract the Table of Contents (TOC) Tree
* **File**: [`hierarchical-processing/toc_v2.py`](file:///home/vijaykumar/Desktop/project2/hierarchical-processing/toc_v2.py)
* **What it does**: Traverses Docling blocks and constructs the hierarchical TOC tree with fine-grained IDs (`S1`, `S2`, `S2.1`...) and lookup tables.
* **How to run**:
  ```bash
  ./venv/bin/python hierarchical-processing/toc_v2.py \
      output/Cigna_Knee_hierarchical.json \
      hierarchical-processing/Knee_toc_output.json \
      hierarchical-processing/knee_toc_tree.txt
  ```
* **Output**:
  - `hierarchical-processing/Knee_toc_output.json` (canonical TOC tree)
  - `hierarchical-processing/knee_toc_tree.txt` (visual text outline)

---

#### Step 3: Chunk the Markdown Document
* **File**: [`hierarchical-processing/chunking_heirarchical.py`](file:///home/vijaykumar/Desktop/project2/hierarchical-processing/chunking_heirarchical.py)
* **What it does**: Splits the hierarchical Markdown into criteria-aware semantic chunks preserving tables, bullet points, and headings.
* **How to run**:
  Ensure the markdown file `Cigna_Knee_hierarchical.md` is in the input folder (e.g., `hierarchical-processing/md/`) and run:
  ```bash
  ./venv/bin/python hierarchical-processing/chunking_heirarchical.py
  ```
* **Output**:
  - `hierarchical-processing/md/chunks/Cigna_Knee_hierarchical_chunks.json`

---

#### Step 4: Map Chunks to the TOC Tree
* **File**: [`hierarchical-processing/chunk_toc_mapper.py`](file:///home/vijaykumar/Desktop/project2/hierarchical-processing/chunk_toc_mapper.py)
* **What it does**: Performs clean block ID join (`block_id_exact`) and heading path alignment to stamp each chunk with its exact `toc_id`.
* **How to run**:
  ```bash
  ./venv/bin/python hierarchical-processing/chunk_toc_mapper.py \
      hierarchical-processing/md/chunks/Cigna_Knee_hierarchical_chunks.json \
      hierarchical-processing/Knee_toc_output.json \
      hierarchical-processing/Cigna_Knee_enriched_chunks.json
  ```
* **Output**:
  - `hierarchical-processing/Cigna_Knee_enriched_chunks.json`

---

#### Step 5: Generate Dense Embeddings
* **File**: [`hierarchical-processing/embedding_with_section.py`](file:///home/vijaykumar/Desktop/project2/hierarchical-processing/embedding_with_section.py)
* **What it does**: Prepends contextual section breadcrumbs and generates 768-dim dense vector embeddings via EmbeddingGemma.
* **How to run**:
  ```bash
  ./venv/bin/python hierarchical-processing/embedding_with_section.py \
      hierarchical-processing/Cigna_Knee_enriched_chunks.json \
      hierarchical-processing/knee_embeddings.npy \
      hierarchical-processing/knee_metadata.json
  ```
* **Output**:
  - `hierarchical-processing/knee_embeddings.npy` (dense vector matrix)
  - `hierarchical-processing/knee_metadata.json` (aligned chunk metadata)

---

#### Step 6: Build the BM25 Lexical Index
* **File**: [`hierarchical-processing/build_bm25.py`](file:///home/vijaykumar/Desktop/project2/hierarchical-processing/build_bm25.py)
* **What it does**: Creates a section-aware Rank-BM25 index over headings and chunk text for exact keyword matching.
* **How to run**:
  ```bash
  ./venv/bin/python hierarchical-processing/build_bm25.py \
      hierarchical-processing/knee_metadata.json \
      hierarchical-processing/knee_bm25.pkl
  ```
* **Output**:
  - `hierarchical-processing/knee_bm25.pkl`

---

#### Step 7: Register in Manifest
Add one JSON entry into [`hierarchical-processing/policies_manifest.json`](file:///home/vijaykumar/Desktop/project2/hierarchical-processing/policies_manifest.json):

```json
{
  "doc_key": "Cigna_Knee",
  "display_name": "Cigna Knee Surgery",
  "toc_file": "Knee_toc_output.json",
  "metadata_file": "knee_metadata.json",
  "embeddings_file": "knee_embeddings.npy",
  "bm25_file": "knee_bm25.pkl"
}
```

---

### Step 8: Done! Ready to Query
The multi-document router in [`retrieval-hierarchical.py`](file:///home/vijaykumar/Desktop/project2/retrieval-hierarchical.py) will instantly recognize the new policy and route queries to it:

```bash
./venv/bin/python retrieval-hierarchical.py "What are the indications for knee surgery?"
```