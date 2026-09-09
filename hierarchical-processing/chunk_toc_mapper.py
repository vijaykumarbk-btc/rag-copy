"""
chunk_toc_mapper.py
------------------
Maps raw Markdown chunks (from chunking_heirarchical.py) to Table of Contents
nodes (from toc_v2.py), enriching each chunk with:
  - toc_id (e.g. S9, S9.1, S9.1.1)
  - docling_section_id (e.g. s0004)
  - canonical heading_path list
  - chunk_index (sequential order)
  - toc_match_method (exact, norm, ancestor, reference_fallback, etc.)

Outputs:
  - <doc>_enriched_chunks.json
  - Console mapping audit & summary statistics.
"""

import os
import sys
import json
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# DEFAULT CONFIGURATION
# ---------------------------------------------------------------------------
DEFAULT_CHUNKS_PATH = "/home/vijaykumar/Desktop/project2/Lumbar/chunks/Cigna_Lumbar_Fusion_hierarchical_chunks.json"
DEFAULT_TOC_PATH = "/home/vijaykumar/Desktop/project2/Lumbar/TOC/Lumbar_toc_output.json"
DEFAULT_OUTPUT_PATH = "/home/vijaykumar/Desktop/project2/Lumbar/toc-mapped-chunks/Cigna_Lumbar_Fusion_enriched_chunks.json"


def normalize_string(s: str) -> str:
    """Normalize text by stripping markdown symbols, extra whitespace, and lowercase."""
    cleaned = re.sub(r"[^\w\s-]", "", s)
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def load_data(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def map_chunks_to_toc(chunks_path: str, toc_path: str, output_path: str = None):
    chunks = load_data(chunks_path)
    toc_data = load_data(toc_path)

    flat_toc = toc_data.get("flat_toc", [])
    heading_to_toc = toc_data.get("heading_path_to_toc_id", {})
    block_to_toc = toc_data.get("block_id_to_toc_id", {})

    # Build TOC node lookup by toc_id for full metadata attachment
    toc_node_by_id = {}
    for item in flat_toc:
        t_id = item.get("toc_id")
        if t_id:
            toc_node_by_id[t_id] = item

    # Normalized lookup map: normalized_breadcrumb -> toc_id
    norm_heading_to_toc = {}
    for k, v in heading_to_toc.items():
        if v:
            norm_heading_to_toc[normalize_string(k)] = v

    # Normalized title map: normalized_title -> toc_id
    norm_title_to_toc = {}
    for item in flat_toc:
        title = item.get("title")
        t_id = item.get("toc_id")
        if title and t_id:
            norm_title_to_toc[normalize_string(title)] = t_id

    enriched_chunks = []
    stats = {
        "block_id_exact": 0,
        "exact_path": 0,
        "normalized_path": 0,
        "title_match": 0,
        "ancestor_fallback": 0,
        "unmapped": 0,
    }

    for idx, chunk in enumerate(chunks):
        sec = chunk.get("section", "").strip()
        norm_sec = normalize_string(sec) if sec else ""
        block_id = chunk.get("block_id") or chunk.get("source_block_id")
        match_method = None
        chosen_toc_id = None

        # Strategy 1: Direct block_id join (authoritative when available)
        if block_id and block_id in block_to_toc and block_to_toc[block_id]:
            chosen_toc_id = block_to_toc[block_id]
            match_method = "block_id_exact"
            stats["block_id_exact"] += 1

        # Strategy 2: Empty section -> unmapped (do not guess or pollute first section)
        elif not sec:
            chosen_toc_id = None
            match_method = "unmapped"

        # Strategy 3: Exact heading breadcrumb match
        elif sec in heading_to_toc and heading_to_toc[sec]:
            chosen_toc_id = heading_to_toc[sec]
            match_method = "exact_path"
            stats["exact_path"] += 1

        # Strategy 4: Normalized heading breadcrumb match
        elif norm_sec in norm_heading_to_toc:
            chosen_toc_id = norm_heading_to_toc[norm_sec]
            match_method = "normalized_path"
            stats["normalized_path"] += 1

        # Strategy 5: Direct or normalized title match
        elif norm_sec in norm_title_to_toc:
            chosen_toc_id = norm_title_to_toc[norm_sec]
            match_method = "title_match"
            stats["title_match"] += 1

        # Strategy 6: Ancestor path match (pop leaf subsections)
        else:
            parts = [p.strip() for p in sec.split(">")]
            for k in range(len(parts) - 1, 0, -1):
                ancestor = " > ".join(parts[:k])
                norm_anc = normalize_string(ancestor)
                if ancestor in heading_to_toc and heading_to_toc[ancestor]:
                    chosen_toc_id = heading_to_toc[ancestor]
                    match_method = "ancestor_fallback"
                    stats["ancestor_fallback"] += 1
                    break
                elif norm_anc in norm_heading_to_toc:
                    chosen_toc_id = norm_heading_to_toc[norm_anc]
                    match_method = "ancestor_fallback"
                    stats["ancestor_fallback"] += 1
                    break
                elif norm_anc in norm_title_to_toc:
                    chosen_toc_id = norm_title_to_toc[norm_anc]
                    match_method = "ancestor_fallback"
                    stats["ancestor_fallback"] += 1
                    break

            if not chosen_toc_id:
                chosen_toc_id = None
                match_method = "unmapped"

        # Attach metadata
        matched_node = toc_node_by_id.get(chosen_toc_id, {})
        heading_path = matched_node.get("heading_path")
        if not heading_path:
            heading_path = [p.strip() for p in sec.split(">")] if sec else []

        docling_section_id = matched_node.get("docling_section_id")

        if not chosen_toc_id:
            stats["unmapped"] += 1

        enriched = {
            "chunk_id": chunk.get("chunk_id", idx),
            "chunk_index": idx,
            "source": chunk.get("source", Path(chunks_path).name),
            "toc_id": chosen_toc_id,
            "toc_match_method": match_method,
            "docling_section_id": docling_section_id,
            "heading_path": heading_path,
            "section": chunk.get("section", ""),
            "parent_section": chunk.get("parent_section", ""),
            "subsection": chunk.get("subsection", ""),
            "section_type": chunk.get("section_type", "other"),
            "chunk_type": chunk.get("chunk_type", "text"),
            "text": chunk.get("text", ""),
        }
        enriched_chunks.append(enriched)

    # Print Summary Audit
    total = len(chunks)
    mapped = total - stats["unmapped"]
    pct = (mapped / total * 100) if total > 0 else 0.0

    print("=" * 60)
    print("TOC CHUNK MAPPING AUDIT")
    print("=" * 60)
    print(f"Source chunks file : {chunks_path}")
    print(f"TOC input file     : {toc_path}")
    print(f"Total chunks       : {total}")
    print(f"Successfully mapped: {mapped} ({pct:.2f}%)")
    print(f"Unmapped chunks    : {stats['unmapped']}")
    print("-" * 60)
    print("Match Method Breakdown:")
    for method, count in stats.items():
        if method != "unmapped":
            m_pct = (count / total * 100) if total > 0 else 0.0
            print(f"  - {method:<20}: {count:>4} ({m_pct:.1f}%)")
    print("=" * 60)

    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(enriched_chunks, f, indent=2, ensure_ascii=False)
        print(f"Enriched chunks successfully saved to: {output_path}")

    return enriched_chunks, stats


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Map hierarchical chunks to Table of Contents IDs.")
    parser.add_argument("chunks", nargs="?", help="Path to input chunks JSON")
    parser.add_argument("toc", nargs="?", help="Path to Table of Contents JSON")
    parser.add_argument("output", nargs="?", help="Path to output enriched chunks JSON")
    parser.add_argument("--chunks", dest="chunks_flag", help="Path to input chunks JSON")
    parser.add_argument("--toc", dest="toc_flag", help="Path to Table of Contents JSON")
    parser.add_argument("--output", dest="out_flag", help="Path to output enriched chunks JSON")
    args = parser.parse_args()

    chunks_in = args.chunks_flag or args.chunks or DEFAULT_CHUNKS_PATH
    toc_in = args.toc_flag or args.toc or DEFAULT_TOC_PATH
    out_file = args.out_flag or args.output or DEFAULT_OUTPUT_PATH

    if not chunks_in or not toc_in or not out_file:
        print("Usage: python chunk_toc_mapper.py <chunks.json> <toc.json> <output_enriched_chunks.json>")
        print("   or: python chunk_toc_mapper.py --chunks <...> --toc <...> --output <...>")
        sys.exit(1)

    map_chunks_to_toc(chunks_in, toc_in, out_file)

