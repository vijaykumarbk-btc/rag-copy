"""
retrieve.py
-----------
Section-Aware TOC-First Scoped Hybrid Retrieval Pipeline.

Flow:
  Stage A — TOC Routing (LLM Call #1):
    Presents compact TOC tree to LLM -> LLM outputs candidate toc_id(s) (e.g. ["S11", "S11.1.3"]).
  Stage B — Scoped Hybrid Retrieval:
    Filters chunks matching candidate toc_id(s) and their descendants.
    Runs BM25 + Dense Cosine Similarity over scoped candidates.
    Fuses results using Reciprocal Rank Fusion (RRF).
  Stage C — Section Expansion & Answering (LLM Call #2):
    Expands top hits to full contiguous section chunks in sequential reading order.
    Sends complete structured context to LLM for final grounded answer.
"""

import os
import sys
import json
import pickle
import re
import numpy as np
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST")
EMBEDDING_MODEL = os.getenv("MODEL", "hf.co/unsloth/embeddinggemma-300m-GGUF:Q8_0")
CHAT_MODEL = os.getenv("CHAT_MODEL", "hf.co/unsloth/medgemma-1.5-4b-it-GGUF:Q8_0")

if not OLLAMA_HOST:
    raise ValueError("OLLAMA_HOST is not set in .env")

client = OpenAI(
    base_url=OLLAMA_HOST,
    api_key="ollama"
)



def clean_llm_response(text: str) -> str:
    """Strip reasoning/thought sections if emitted by the model."""
    # Strip <thought>...</thought> or <think>...</think>
    text = re.sub(r"<(?:thought|think)>.*?</(?:thought|think)>", "", text, flags=re.DOTALL)
    # Strip leading 'thought\n...' if any
    text = re.sub(r"^thought\s+.*?(?=(?:```|\[|\n\n[A-Z]))", "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


def tokenize(text: str) -> list[str]:
    text = text.lower()
    return re.findall(r"[a-z0-9]+(?:[-.][a-z0-9]+)*", text)


def cosine_similarity(vec_a: np.ndarray, matrix_b: np.ndarray) -> np.ndarray:
    norm_a = np.linalg.norm(vec_a)
    if norm_a == 0:
        return np.zeros(len(matrix_b), dtype=np.float32)
    norm_b = np.linalg.norm(matrix_b, axis=1)
    norm_b[norm_b == 0] = 1e-9
    return np.dot(matrix_b, vec_a) / (norm_a * norm_b)


def render_compact_toc(flat_toc: list[dict]) -> str:
    """Format a clean, compact TOC representation for the routing LLM."""
    lines = []
    for item in flat_toc:
        t_id = item.get("toc_id")
        title = item.get("title", "").strip()
        page = item.get("page")
        if not t_id or not title:
            continue
        level = item.get("heading_level", 1)
        indent = "  " * max(0, level - 1)
        page_str = f" (p.{page})" if page else ""
        lines.append(f"{indent}[{t_id}] {title}{page_str}")
    return "\n".join(lines)


def route_query_to_multi_doc_toc(query: str, registry, chat_model: str = CHAT_MODEL) -> tuple[str, list[str]]:
    """
    Stage A: Use LLM to select target document key and relevant toc_id(s)
    across all registered policy documents.
    """
    compact_tocs = registry.get_compact_tocs()
    doc_keys_str = ", ".join(f'"{k}"' for k in registry.documents.keys())

    prompt = f"""You are an expert clinical search assistant. Given the following Table of Contents of medical coverage policy documents and a clinical question, identify:
1. The most relevant document key (one of: {doc_keys_str}). If NONE of the policies cover or are relevant to the question, set "document_key": null and "toc_ids": [].
2. The specific section ID(s) (e.g. ["S9", "S9.1", "S9.1.1"] or ["S11", "S11.1"])

### Documents & Table of Contents:
{compact_tocs}

### Clinical Question:
{query}

### Output Instructions:
Output strictly a JSON object with keys "document_key" and "toc_ids":
{{"document_key": "...", "toc_ids": ["S..."]}}
"""

    try:
        response = client.chat.completions.create(
            model=chat_model,
            messages=[
                {"role": "system", "content": "You output strictly valid JSON objects with document_key and toc_ids."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0
        )
        content = clean_llm_response(response.choices[0].message.content)
        data = None
        try:
            import json_repair
            data = json_repair.loads(content)
        except Exception:
            pass

        if not isinstance(data, dict):
            json_match = re.search(r"\{.*?\}", content, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group(0))
                except Exception:
                    pass

        if isinstance(data, dict):
            doc_key = data.get("document_key")
            toc_ids = data.get("toc_ids", [])
            if doc_key in registry.documents:
                valid_ids = [str(x).strip() for x in toc_ids if re.match(r"^S\d+(?:\.\d+)*$", str(x).strip())]
                return doc_key, valid_ids
    except Exception as e:
        print(f"[Warning] Multi-doc TOC routing LLM call encountered error: {e}")

    return None, []


def route_query_to_toc(query: str, flat_toc: list[dict], chat_model: str = CHAT_MODEL) -> list[str]:
    """
    Stage A (Single-Doc): Use LLM to select relevant toc_id(s) based on a single Table of Contents.
    """
    compact_toc = render_compact_toc(flat_toc)
    prompt = f"""You are an expert clinical search assistant. Given the following Table of Contents of a medical coverage policy document and a clinical question, identify the most relevant section ID(s) (e.g. S9, S11, S11.1.3) needed to answer the question.

### Document Table of Contents:
{compact_toc}

### Clinical Question:
{query}

### Instructions:
- Output ONLY a valid JSON array of strings containing the relevant section IDs (e.g. ["S11", "S11.1.3"]).
- If unsure or if the question spans multiple areas, include the top 2-3 most relevant section IDs.
- Format your response strictly as JSON: ["S..."]
"""

    try:
        response = client.chat.completions.create(
            model=chat_model,
            messages=[
                {"role": "system", "content": "You output strictly valid JSON lists of section IDs like [\"S11\"]."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0
        )
        content = clean_llm_response(response.choices[0].message.content)
        json_match = re.search(r"\[\s*\"[^\"]+\"(?:\s*,\s*\"[^\"]+\")*\s*\]", content, re.DOTALL)
        if json_match:
            chosen_ids = json.loads(json_match.group(0))
            if isinstance(chosen_ids, list):
                valid_ids = [str(x).strip() for x in chosen_ids if re.match(r"^S\d+(?:\.\d+)*$", str(x).strip())]
                if valid_ids:
                    return valid_ids
    except Exception as e:
        print(f"[Warning] TOC routing LLM call encountered error: {e}")

    return []


def scoped_hybrid_search(
    query: str,
    chosen_toc_ids: list[str],
    metadata: list[dict],
    embeddings: np.ndarray,
    bm25_data: dict,
    top_k: int = 5,
    rrf_k: int = 60
) -> list[dict]:
    """
    Stage B: Scoped Dense + BM25 search with Reciprocal Rank Fusion over candidate chunks.
    """
    if chosen_toc_ids:
        candidate_indices = [
            i for i, row in enumerate(metadata)
            if row.get("toc_id") and any(
                row["toc_id"] == chosen or row["toc_id"].startswith(chosen + ".")
                for chosen in chosen_toc_ids
            )
        ]
    else:
        candidate_indices = []

    if not candidate_indices:
        print("[Info] No active TOC filter or 0 candidates found; searching full corpus.")
        candidate_indices = list(range(len(metadata)))

    print(f"[Stage B] Searching {len(candidate_indices)} candidate chunks (out of {len(metadata)} total)...")

    # 1. Dense Cosine Similarity
    query_resp = client.embeddings.create(model=EMBEDDING_MODEL, input=query)
    query_vec = np.array(query_resp.data[0].embedding, dtype=np.float32)

    sub_embeddings = embeddings[candidate_indices]
    dense_scores = cosine_similarity(query_vec, sub_embeddings)
    dense_ranked_order = np.argsort(-dense_scores)

    dense_rank_map = {}
    for rank, local_idx in enumerate(dense_ranked_order, 1):
        global_idx = candidate_indices[local_idx]
        dense_rank_map[global_idx] = rank

    # 2. BM25 Search
    bm25 = bm25_data.get("bm25") if isinstance(bm25_data, dict) else bm25_data
    query_tokens = tokenize(query)
    bm25_scores = bm25.get_scores(query_tokens)
    candidate_bm25_scores = [(global_idx, bm25_scores[global_idx]) for global_idx in candidate_indices]
    candidate_bm25_scores.sort(key=lambda x: x[1], reverse=True)

    bm25_rank_map = {}
    for rank, (global_idx, score) in enumerate(candidate_bm25_scores, 1):
        bm25_rank_map[global_idx] = rank

    # 3. Reciprocal Rank Fusion (RRF)
    fused_results = []
    for global_idx in candidate_indices:
        r_dense = dense_rank_map.get(global_idx, len(candidate_indices) + 1)
        r_bm25 = bm25_rank_map.get(global_idx, len(candidate_indices) + 1)
        rrf_score = (1.0 / (rrf_k + r_dense)) + (1.0 / (rrf_k + r_bm25))

        fused_results.append({
            "chunk_idx": global_idx,
            "chunk": metadata[global_idx],
            "rrf_score": rrf_score,
            "dense_rank": r_dense,
            "bm25_rank": r_bm25,
        })

    fused_results.sort(key=lambda x: x["rrf_score"], reverse=True)
    return fused_results[:top_k]


def expand_section_context(top_hits: list[dict], metadata: list[dict]) -> list[dict]:
    """
    Stage C helper: Retrieve all contiguous chunks for matched toc_ids to provide complete criteria context.
    """
    hit_toc_ids = set()
    for hit in top_hits:
        t_id = hit["chunk"].get("toc_id")
        if t_id:
            hit_toc_ids.add(t_id)

    expanded_chunks = []
    seen_indices = set()

    for idx, item in enumerate(metadata):
        if item.get("toc_id") in hit_toc_ids:
            if idx not in seen_indices:
                seen_indices.add(idx)
                expanded_chunks.append(item)

    if not expanded_chunks:
        expanded_chunks = [h["chunk"] for h in top_hits]

    return expanded_chunks


def answer_query(
    query: str,
    context_chunks: list[dict],
    chat_model: str = CHAT_MODEL
) -> str:
    """
    Stage C: Generate grounded clinical answer using retrieved section context.
    """
    formatted_context = []
    for i, c in enumerate(context_chunks, 1):
        sec = c.get("section") or " > ".join(c.get("heading_path", []))
        toc_id = c.get("toc_id", "N/A")
        text = c.get("text", "")
        formatted_context.append(f"--- Section [{toc_id}] {sec} ---\n{text}")

    context_str = "\n\n".join(formatted_context)

    prompt = f"""You are a clinical decision support assistant analyzing medical coverage policies.
Answer the question accurately based ONLY on the provided policy context.
Cite the relevant section IDs (e.g. [S9.1], [S11]) when citing criteria or requirements.

### Medical Policy Context:
{context_str}

### Question:
{query}

### Answer:"""

    response = client.chat.completions.create(
        model=chat_model,
        messages=[
            {"role": "system", "content": "You are a precise clinical medical policy analyst."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1
    )
    raw_ans = response.choices[0].message.content
    return clean_llm_response(raw_ans)


def run_retrieval_pipeline(query: str, doc_key: str = None):
    print("=" * 70)
    print(f"QUERY: {query}")
    print(f"Embedding Model: {EMBEDDING_MODEL}")
    print(f"Chat Model     : {CHAT_MODEL}")
    print("=" * 70)

    from document_registry import DocumentRegistry
    registry = DocumentRegistry()

    # Stage A: TOC Routing
    print("\n[Stage A] Routing query through TOC...")
    if doc_key and doc_key in registry.documents:
        selected_doc_key = doc_key
        doc_info = registry.get_document(selected_doc_key)
        with open(doc_info["toc_file"], "r", encoding="utf-8") as f:
            toc_data = json.load(f)
        chosen_toc_ids = route_query_to_toc(query, toc_data.get("flat_toc", []))
    else:
        selected_doc_key, chosen_toc_ids = route_query_to_multi_doc_toc(query, registry)

    if not selected_doc_key or selected_doc_key not in registry.documents:
        print(f"[Notice] No matching policy document identified for query: '{query}'")
        msg = f"No registered medical coverage policy was identified that covers the clinical question: '{query}'."
        print(msg)
        return {
            "query": query,
            "policy": None,
            "chosen_toc_ids": [],
            "top_hits": [],
            "expanded_context_count": 0,
            "answer": msg
        }

    doc_info = registry.get_document(selected_doc_key)
    with open(doc_info["toc_file"], "r", encoding="utf-8") as f:
        toc_data = json.load(f)

    print(f"Selected Policy : {selected_doc_key} ({doc_info['display_name']})")
    print(f"Selected TOC IDs: {chosen_toc_ids}")

    # Load data for selected policy
    with open(doc_info["metadata_file"], "r", encoding="utf-8") as f:
        metadata = json.load(f)
    embeddings = np.load(doc_info["embeddings_file"])
    with open(doc_info["bm25_file"], "rb") as f:
        bm25_data = pickle.load(f)

    # Stage B: Scoped Hybrid Search
    print("\n[Stage B] Running Scoped Hybrid Retrieval (BM25 + Dense RRF)...")
    top_hits = scoped_hybrid_search(
        query=query,
        chosen_toc_ids=chosen_toc_ids,
        metadata=metadata,
        embeddings=embeddings,
        bm25_data=bm25_data,
        top_k=5
    )

    print("\nTop Retrieved Hits:")
    for rank, hit in enumerate(top_hits, 1):
        c = hit["chunk"]
        print(f"  {rank}. [{c.get('toc_id')}] (RRF: {hit['rrf_score']:.4f}, Dense Rank: {hit['dense_rank']}, BM25 Rank: {hit['bm25_rank']})")
        print(f"     Section: {c.get('section')[:80]}")

    # Stage C: Section Expansion & LLM Generation
    print("\n[Stage C] Expanding sections & generating grounded answer...")
    expanded_context = expand_section_context(top_hits, metadata)
    print(f"Expanded to {len(expanded_context)} contiguous section chunks.")

    answer = answer_query(query, expanded_context)

    print("\n" + "=" * 70)
    print("FINAL CLINICAL ANSWER:")
    print("=" * 70)
    print(answer)
    print("=" * 70)

    return {
        "query": query,
        "policy": selected_doc_key,
        "chosen_toc_ids": chosen_toc_ids,
        "top_hits": top_hits,
        "expanded_context_count": len(expanded_context),
        "answer": answer
    }


if __name__ == "__main__":
    doc_arg = None
    query_parts = []
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--doc" and i + 1 < len(args):
            doc_arg = args[i + 1]
            i += 2
        else:
            query_parts.append(args[i])
            i += 1

    if query_parts:
        test_query = " ".join(query_parts)
    else:
        test_query = input("Enter your clinical query: ")

    run_retrieval_pipeline(test_query, doc_key=doc_arg)

