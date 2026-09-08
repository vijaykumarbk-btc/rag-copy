import os
import json
import pickle
import numpy as np

from openai import OpenAI
from dotenv import load_dotenv

from bm25_index import tokenize


# ============================================================
# CONFIG
# ============================================================

load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST")
MODEL = os.getenv("MODEL")

EMBEDDINGS_FILE = os.getenv("EMBEDDINGS_FILE")
METADATA_FILE = os.getenv("METADATA_FILE")
BM25_INDEX_FILE = os.getenv("BM25_INDEX_FILE")


if not OLLAMA_HOST:
    raise ValueError("OLLAMA_HOST is not set in .env")

if not MODEL:
    raise ValueError("MODEL is not set in .env")

if not EMBEDDINGS_FILE:
    raise ValueError("EMBEDDINGS_FILE is not set in .env")

if not METADATA_FILE:
    raise ValueError("METADATA_FILE is not set in .env")

if not BM25_INDEX_FILE:
    raise ValueError("BM25_INDEX_FILE is not set in .env")


client = OpenAI(
    base_url=OLLAMA_HOST,
    api_key="ollama"
)


# ============================================================
# LOAD INDEX
# ============================================================

def resolve_index_files(policy_hint=None):
    """
    Resolve which embeddings, metadata, and BM25 index files to load
    dynamically using DocumentRegistry without any hardcoded procedure strings.
    """
    try:
        import sys
        hp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hierarchical-processing")
        if hp_dir not in sys.path:
            sys.path.append(hp_dir)
        from document_registry import DocumentRegistry
        reg = DocumentRegistry(base_dir=hp_dir)

        if policy_hint and policy_hint in reg.documents:
            doc = reg.documents[policy_hint]
            return doc["embeddings_file"], doc["metadata_file"], doc["bm25_file"]

        # Case-insensitive lookup or partial display name match
        for k, doc in reg.documents.items():
            if policy_hint and (k.lower() == str(policy_hint).lower() or str(policy_hint).lower() in doc["display_name"].lower()):
                return doc["embeddings_file"], doc["metadata_file"], doc["bm25_file"]
    except Exception:
        pass

    if policy_hint is None and EMBEDDINGS_FILE and os.path.exists(EMBEDDINGS_FILE):
        return EMBEDDINGS_FILE, METADATA_FILE, BM25_INDEX_FILE

    raise ValueError(f"Could not resolve index files for policy: {policy_hint}")


def resolve_toc_file(policy_hint=None) -> str:
    """Resolve the TOC JSON file path for a policy."""
    try:
        import sys
        hp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hierarchical-processing")
        if hp_dir not in sys.path:
            sys.path.append(hp_dir)
        from document_registry import DocumentRegistry
        reg = DocumentRegistry(base_dir=hp_dir)

        if policy_hint and policy_hint in reg.documents:
            return reg.documents[policy_hint].get("toc_file")

        for k, doc in reg.documents.items():
            if policy_hint and (k.lower() == str(policy_hint).lower() or str(policy_hint).lower() in doc["display_name"].lower()):
                return doc.get("toc_file")
    except Exception:
        pass
    return None


def get_descendant_toc_ids(toc_file: str, candidate_toc_ids: list[str]) -> set[str]:
    """
    Traverse the authoritative TOC tree to collect the target TOC IDs and all their
    descendants, ensuring robust tree-based hierarchical scoping across all Cigna PDFs.
    """
    if not candidate_toc_ids:
        return set()

    target_set = set(str(t).strip() for t in candidate_toc_ids if t)
    allowed = set(target_set)

    if toc_file and os.path.exists(toc_file):
        try:
            with open(toc_file, "r", encoding="utf-8") as f:
                toc_data = json.load(f)
            toc_tree = toc_data.get("toc_tree", [])

            def collect_subnodes(node, active):
                node_id = str(node.get("toc_id", "")).strip()
                is_active = active or (node_id in target_set)
                if is_active and node_id:
                    allowed.add(node_id)
                for child in node.get("children", []):
                    collect_subnodes(child, is_active)

            for root_node in toc_tree:
                collect_subnodes(root_node, False)
        except Exception:
            pass

    return allowed


def load_index(policy_hint=None):
    emb_path, meta_path, bm25_path = resolve_index_files(policy_hint)

    embeddings = np.load(emb_path)

    with open(meta_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    with open(bm25_path, "rb") as f:
        bm25_data = pickle.load(f)
        # Handle dict format or raw BM25Okapi
        bm25 = bm25_data.get("bm25") if isinstance(bm25_data, dict) else bm25_data

    if embeddings.shape[0] != len(metadata):
        raise ValueError(
            f"Mismatch: {embeddings.shape[0]} embeddings "
            f"but {len(metadata)} metadata entries"
        )

    return embeddings, metadata, bm25


# ============================================================
# EMBED QUERY
# ============================================================

def embed_query(query):

    response = client.embeddings.create(
        model=MODEL,
        input=query
    )

    return np.asarray(
        response.data[0].embedding,
        dtype=np.float32
    )


# ============================================================
# COSINE SIMILARITY
# ============================================================

def cosine_similarity(query_vec, matrix):

    query_norm = np.linalg.norm(query_vec)

    if query_norm == 0:
        raise ValueError("Query embedding has zero magnitude.")

    query_vec = query_vec / query_norm

    matrix_norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix_norms = np.maximum(matrix_norms, 1e-12)

    normalized_matrix = matrix / matrix_norms

    return normalized_matrix @ query_vec


# ============================================================
# NORMALIZE
# ============================================================

def normalize(scores):

    scores = np.asarray(scores, dtype=np.float32)

    min_score = scores.min()
    max_score = scores.max()

    if max_score - min_score < 1e-9:
        return np.zeros_like(scores)

    return (scores - min_score) / (max_score - min_score)


# ============================================================
# COMPLETE SIBLING CONDITIONS (lightweight, not full section)
# ============================================================

def complete_sibling_conditions(direct_indices, metadata):
    """
    For each directly matched chunk that is a genuine 'condition'
    subsection (e.g. Radiculopathy, Myelopathy, Unremitting Neck
    Pain...) -- identified by subsection being non-empty AND
    different from parent_section -- pull in ONLY its sibling
    condition subsections under the same parent_section.

    This deliberately excludes:
      - section headers (subsection == parent_section)
      - ToC / codes / references chunks (subsection == "")

    So it stays small: usually +1 or +2 chunks, never a whole section.
    """

    direct_index_set = set(direct_indices)
    result_indices = list(direct_indices)

    # Build parent_section -> [indices of real condition subsections]
    condition_groups = {}

    for idx, chunk in enumerate(metadata):

        subsection = chunk.get("subsection", "")
        parent_section = chunk.get("parent_section", "")

        if not subsection or not parent_section:
            continue

        if subsection == parent_section:
            continue  # header chunk, not a real condition subsection

        condition_groups.setdefault(parent_section, []).append(idx)

    added = set()

    for idx in direct_indices:

        chunk = metadata[idx]
        parent_section = chunk.get("parent_section", "")

        if not parent_section:
            continue

        for sibling_idx in condition_groups.get(parent_section, []):

            if sibling_idx not in direct_index_set and sibling_idx not in added:
                result_indices.append(sibling_idx)
                added.add(sibling_idx)

    return result_indices


# ============================================================
# HYBRID SEARCH WITH SIBLING COMPLETION
# ============================================================

def search(
    query,
    policy_hint=None,
    top_k=10,
    alpha=0.5,
    mode="keyword"
):
    """
    Flat top-k retrieval (bounded, predictable prompt size) with
    lightweight sibling-condition completion: if a matched chunk
    is a condition subsection (e.g. Radiculopathy), its sibling
    condition subsections under the same guideline (e.g. Myelopathy)
    are pulled in too, since guidelines often say "EITHER condition
    A OR condition B" and BM25/embeddings can easily miss one side
    due to differing vocabulary.

    mode:
        "keyword"  -> rank purely by BM25 score
        "semantic" -> rank purely by cosine similarity
        "hybrid"   -> weighted blend (alpha * semantic + (1-alpha) * keyword)
    """

    embeddings, metadata, bm25 = load_index(policy_hint=policy_hint)

    num_chunks = len(metadata)

    semantic_scores = np.zeros(num_chunks, dtype=np.float32)
    keyword_scores = np.zeros(num_chunks, dtype=np.float32)

    # --------------------------------------------------------
    # Semantic
    # --------------------------------------------------------

    if mode in ("hybrid", "semantic"):
        query_vector = embed_query(query)
        semantic_scores = cosine_similarity(query_vector, embeddings)

    # --------------------------------------------------------
    # BM25
    # --------------------------------------------------------

    if mode in ("hybrid", "keyword"):
        tokenized_query = tokenize(query)
        keyword_scores = np.asarray(
            bm25.get_scores(tokenized_query),
            dtype=np.float32
        )

    # --------------------------------------------------------
    # Final score
    # --------------------------------------------------------

    if mode == "semantic":
        final_scores = semantic_scores

    elif mode == "keyword":
        final_scores = keyword_scores

    elif mode == "hybrid":
        semantic_normalized = normalize(semantic_scores)
        keyword_normalized = normalize(keyword_scores)

        final_scores = (
            alpha * semantic_normalized
            + (1.0 - alpha) * keyword_normalized
        )

    else:
        raise ValueError("mode must be 'hybrid', 'semantic', or 'keyword'")

    # --------------------------------------------------------
    # TOP-K DIRECT MATCHES
    # --------------------------------------------------------

    ranked_indices = np.argsort(final_scores)[::-1]

    direct_indices = ranked_indices[:top_k].tolist()

    direct_index_set = set(direct_indices)

    # --------------------------------------------------------
    # COMPLETE ANY SIBLING CONDITIONS (lightweight)
    # --------------------------------------------------------

    final_indices = complete_sibling_conditions(direct_indices, metadata)

    # Preserve document/chunk order
    final_indices = sorted(
        final_indices,
        key=lambda idx: metadata[idx].get("chunk_id", idx)
    )

    # --------------------------------------------------------
    # Build results
    # --------------------------------------------------------

    results = []

    for idx in final_indices:

        chunk = metadata[idx]

        results.append({
            "score": float(final_scores[idx]),
            "semantic_score": float(semantic_scores[idx]),
            "keyword_score": float(keyword_scores[idx]),
            "chunk_id": chunk.get("chunk_id"),
            "source": chunk.get("source"),
            "section": chunk.get("section"),
            "parent_section": chunk.get("parent_section"),
            "subsection": chunk.get("subsection"),
            "section_type": chunk.get("section_type"),
            "chunk_type": chunk.get("chunk_type"),
            "text": chunk.get("text"),
            "direct_match": idx in direct_index_set,
            "completed": idx not in direct_index_set,
        })

    return results


# ============================================================
# SCOPED HYBRID SEARCH (TOC-Restricted)
# ============================================================

def scoped_search(
    query: str,
    policy_hint: str = None,
    candidate_toc_ids: list[str] = None,
    top_k: int = 8,
    alpha: float = 0.5,
    mode: str = "hybrid"
):
    """
    Search strictly within chunks tagged with specific toc_ids
    (e.g. S9.1, S9.1.1, S11) and complete sibling conditions.
    """
    embeddings, metadata, bm25 = load_index(policy_hint=policy_hint)
    num_chunks = len(metadata)

    if candidate_toc_ids:
        toc_file = resolve_toc_file(policy_hint)
        allowed_ids = get_descendant_toc_ids(toc_file, candidate_toc_ids)

        candidate_indices = [
            i for i, row in enumerate(metadata)
            if row.get("toc_id") and (
                row["toc_id"] in allowed_ids
                or any(row["toc_id"].startswith(chosen + ".") for chosen in candidate_toc_ids)
            )
        ]

        # Strict scoping: if candidate_toc_ids was specified and matched 0 chunks,
        # return empty list rather than falling back to searching all chunks in the document.
        if not candidate_indices:
            return []
    else:
        candidate_indices = list(range(num_chunks))

    semantic_scores = np.zeros(num_chunks, dtype=np.float32)
    keyword_scores = np.zeros(num_chunks, dtype=np.float32)

    if mode in ("hybrid", "semantic"):
        query_vector = embed_query(query)
        semantic_scores = cosine_similarity(query_vector, embeddings)

    if mode in ("hybrid", "keyword"):
        tokenized_query = tokenize(query)
        keyword_scores = np.asarray(
            bm25.get_scores(tokenized_query),
            dtype=np.float32
        )

    if mode == "semantic":
        final_scores = semantic_scores
    elif mode == "keyword":
        final_scores = keyword_scores
    else:
        semantic_normalized = normalize(semantic_scores)
        keyword_normalized = normalize(keyword_scores)
        final_scores = (
            alpha * semantic_normalized
            + (1.0 - alpha) * keyword_normalized
        )

    ranked_candidates = sorted(candidate_indices, key=lambda idx: final_scores[idx], reverse=True)
    direct_indices = ranked_candidates[:top_k]
    direct_index_set = set(direct_indices)

    final_indices = complete_sibling_conditions(direct_indices, metadata)
    final_indices = sorted(
        final_indices,
        key=lambda idx: metadata[idx].get("chunk_id", idx)
    )

    results = []
    for idx in final_indices:
        chunk = metadata[idx]
        results.append({
            "score": float(final_scores[idx]),
            "semantic_score": float(semantic_scores[idx]),
            "keyword_score": float(keyword_scores[idx]),
            "chunk_id": chunk.get("chunk_id"),
            "source": chunk.get("source"),
            "section": chunk.get("section"),
            "parent_section": chunk.get("parent_section"),
            "subsection": chunk.get("subsection"),
            "section_type": chunk.get("section_type"),
            "chunk_type": chunk.get("chunk_type"),
            "text": chunk.get("text"),
            "toc_id": chunk.get("toc_id"),
            "direct_match": idx in direct_index_set,
            "completed": idx not in direct_index_set,
        })

    return results


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    query = input("Enter your query: ")

    results = search(
        query=query,
        top_k=10,
        alpha=0.5,
        mode="keyword"
    )

    print(f"\nQuery: {query}")
    print(f"\nReturned {len(results)} chunks\n")

    for i, result in enumerate(results):

        print(f"--- Result {i + 1} ---")
        print(f"Chunk ID: {result.get('chunk_id')}")
        print(f"Parent Section: {result.get('parent_section')}")
        print(f"Section: {result.get('section')}")
        print(f"Subsection: {result.get('subsection')}")
        print(f"Direct Match: {result.get('direct_match')}")
        print(f"Completed: {result.get('completed')}")
        print(f"Score: {result.get('score'):.4f}")
        print(f"Semantic: {result.get('semantic_score'):.4f}")
        print(f"BM25: {result.get('keyword_score'):.4f}")
        print(f"Text:\n{result.get('text', '')[:500]}...")
        print()