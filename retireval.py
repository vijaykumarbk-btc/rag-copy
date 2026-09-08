import os
from datetime import datetime
from groq import Groq
from dotenv import load_dotenv
from hybrid_search import search


load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEN_MODEL = os.getenv("GEN_MODEL")

if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY is not set in .env")

if not GEN_MODEL:
    raise ValueError("GEN_MODEL is not set in .env")

client = Groq(api_key=GROQ_API_KEY)

OUTPUT_DIR = "data/results_new"


def build_context(results):
    blocks = []
    for i, r in enumerate(results):
        header = f"[{i + 1}] Section: {r['parent_section']} > {r['section']}"
        blocks.append(f"{header}\n{r['text']}")
    return "\n\n---\n\n".join(blocks)


def build_prompt(query, context):
    return f"""You are a clinical policy assistant that answers questions strictly from medical prior authorization guideline excerpts. These guidelines cover medical and surgical procedures often organized as parent sections with multiple named subsections under policy headings.

Rules:
1. Answer using ONLY the context below. If the context does not fully answer the question, state that explicitly — do not guess, infer, or use outside medical knowledge.
2. Be EXHAUSTIVE. If multiple context blocks or subsections fall under the same parent section as the question topic, include criteria from ALL of them — not just the first or most detailed one.
3. Criteria are not always a bulleted list. A subsection that says a procedure "is considered medically necessary when ALL/ANY criteria in [another section] have been met" IS a criterion in itself — it means that section's requirements must also be satisfied. Always include these cross-referencing statements as their own bullet, naming which section they point to, even if that section's actual bullets are not present in the context.
4. Never silently drop, merge, or paraphrase away a subsection just because it isn't the primary subject of the question, or because it lacks its own bulleted list. If it's under the same parent section, include it.
5. Preserve the structure of the source. Keep distinct bullets/subsections separate rather than compressing them into one paraphrased sentence.
6. Do not draw conclusions, combine rules, or state criteria that are not explicitly written in the context — even if it seems clinically reasonable.
7. When you use information from a context block, cite it using its number, like [1] or [2]. If one block supports multiple bullets, cite it on each one individually.
8. If the context includes content about a procedure or deformity type clearly unrelated to the question (different parent section entirely, no shared heading), leave it out.

Context:
{context}

Question: {query}

Answer using this format:
- Every bullet per distinct subsection/criterion found in the context relevant to the question's parent section, each with its citation. Include cross-referencing requirements ("criteria must be met in Section X") as their own bullet even without their own enumerated list.
- If nothing relevant is found in the context, say so directly instead of giving a partial or empty answer.

Answer:"""

def generate_answer(query, top_k=10, alpha=0.5, mode="hybrid"):
    results = search(query, top_k=top_k, alpha=alpha, mode=mode)

    context = build_context(results)
    prompt = build_prompt(query, context)

    response = client.chat.completions.create(
        model=GEN_MODEL,
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0.1,
        reasoning_effort="none",
    )

    answer = response.choices[0].message.content

    return {
        "query": query,
        "answer": answer,
        "sources": results,
        "mode": mode,
        "alpha": alpha,
        "top_k": top_k,
    }


def write_markdown_report(result, filepath):
    lines = []

    lines.append(f"# Query: {result['query']}\n")
    lines.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                  f"| mode={result['mode']} | alpha={result['alpha']} | top_k={result['top_k']}*\n")

    lines.append("## Answer\n")
    lines.append(result["answer"] + "\n")

    lines.append("## Retrieved Sources\n")
    for i, r in enumerate(result["sources"]):
        lines.append(f"### [{i + 1}] {r['parent_section']} > {r['section']}")
        lines.append(
            f"**Scores** — hybrid: `{r['score']:.4f}` "
            f"| semantic: `{r['semantic_score']:.4f}` "
            f"| bm25: `{r['keyword_score']:.4f}`\n"
        )
        lines.append("```")
        lines.append(r["text"].strip())
        lines.append("```\n")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def slugify(text, max_len=50):
    slug = "".join(c if c.isalnum() or c == " " else "" for c in text)
    slug = "_".join(slug.split())
    return slug[:max_len]


if __name__ == "__main__":
    query = input("Enter your query: ")

    result = generate_answer(query, top_k=10)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{slugify(query)}.md"
    filepath = os.path.join(OUTPUT_DIR, filename)

    write_markdown_report(result, filepath)

    print(f"\nReport saved to: {filepath}")
    print("\n=== ANSWER (preview) ===")
    print(result["answer"])