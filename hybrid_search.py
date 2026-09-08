import os
import json
import pickle
import numpy as np
from openai import OpenAI
from dotenv import load_dotenv
from bm25_index import tokenize


load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST")
MODEL = os.getenv("MODEL")

if not OLLAMA_HOST:
    raise ValueError("OLLAMA_HOST is not set in .env")

if not MODEL:
    raise ValueError("MODEL is not set in .env")

client = OpenAI(
    base_url=OLLAMA_HOST,
    api_key="ollama"
)

EMBEDDINGS_FILE = "/home/vijaykumar/Desktop/project/hierarchical-processing/acdf_embeddings.npy"
METADATA_FILE = "/home/vijaykumar/Desktop/project/hierarchical-processing/acdf_metadata.json"
BM25_INDEX_FILE = "/home/vijaykumar/Desktop/project/hierarchical-processing/acdf_bm25.pkl"


def load_index():
    embeddings = np.load(EMBEDDINGS_FILE)

    with open(METADATA_FILE, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    with open(BM25_INDEX_FILE, "rb") as f:
        bm25 = pickle.load(f)

    if embeddings.shape[0] != len(metadata):
        raise ValueError(
            f"Mismatch: {embeddings.shape[0]} embeddings "
            f"but {len(metadata)} metadata entries"
        )

    return embeddings, metadata, bm25


def embed_query(query):
    response = client.embeddings.create(
        model=MODEL,
        input=query
    )
    return np.array(response.data[0].embedding, dtype=np.float32)


def cosine_similarity(query_vec, matrix):
    query_norm = query_vec / np.linalg.norm(query_vec)
    matrix_norms = matrix / np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix_norms @ query_norm


def normalize(scores):
    """Min-max normalize to [0, 1] so BM25 and cosine scores are comparable."""
    scores = np.array(scores, dtype=np.float32)
    min_s, max_s = scores.min(), scores.max()
    if max_s - min_s < 1e-9:
        return np.zeros_like(scores)
    return (scores - min_s) / (max_s - min_s)


def search(query, top_k=5, alpha=0.5, mode="hybrid"):
    """
    mode: "hybrid" | "semantic" | "keyword"
    alpha: weight for semantic score in hybrid mode (1-alpha goes to BM25)
    """
    embeddings, metadata, bm25 = load_index()

    semantic_scores = np.zeros(len(metadata))
    keyword_scores = np.zeros(len(metadata))

    if mode in ("hybrid", "semantic"):
        query_vec = embed_query(query)
        semantic_scores = cosine_similarity(query_vec, embeddings)

    if mode in ("hybrid", "keyword"):
        tokenized_query = tokenize(query)
        keyword_scores = np.array(bm25.get_scores(tokenized_query))

    if mode == "semantic":
        final_scores = semantic_scores
    elif mode == "keyword":
        final_scores = keyword_scores
    else:  # hybrid
        norm_semantic = normalize(semantic_scores)
        norm_keyword = normalize(keyword_scores)
        final_scores = alpha * norm_semantic + (1 - alpha) * norm_keyword

    top_indices = np.argsort(final_scores)[::-1][:top_k]

    results = []
    for idx in top_indices:
        results.append({
            "score": float(final_scores[idx]),
            "semantic_score": float(semantic_scores[idx]),
            "keyword_score": float(keyword_scores[idx]),
            "chunk_id": metadata[idx].get("chunk_id"),
            "section": metadata[idx].get("section"),
            "parent_section": metadata[idx].get("parent_section"),
            "text": metadata[idx].get("text"),
        })

    return results


if __name__ == "__main__":
    query = input("Enter your query: ")

    results = search(query, top_k=10, alpha=0.5, mode="hybrid")

    print(f"\nTop {len(results)} results for: '{query}'\n")

    for i, r in enumerate(results):
        print(f"--- Result {i + 1} (hybrid: {r['score']:.4f} | semantic: {r['semantic_score']:.4f} | bm25: {r['keyword_score']:.4f}) ---")
        print(f"Section: {r['parent_section']} > {r['section']}")
        print(f"Text:\n{r['text'][:300]}...")
        print()