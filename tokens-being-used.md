Viewed retrieval-hierarchical.py:145-220

### Why Your Output Tokens Exploded to ~5k

There are **3 specific reasons** why token generation expanded:

---

### 1. Reasoning Models Generate Huge `<think>` Traces
The active model (`qwen/qwen3.6-27b` on Groq or local `medgemma`) is a **reasoning model**.
- When `max_tokens` was increased to `6144`, reasoning models utilize that full ceiling to generate **2,500 to 4,000 tokens of internal chain-of-thought** inside `<think>...</think>` before producing the JSON.
- Even though the final JSON payload might only be ~800 tokens, the total generated output tokens (thinking + JSON) reached **~4,500 – 5,500 tokens**.

---

### 2. Stage 2 (TOC Routing) Inherited the 6k Ceiling
Every query runs **two LLM calls**:
1. **Stage 2 (TOC Routing)**: Only needs ~50 tokens (`{"document_key": "Cigna_ACDF", "toc_ids": ["S10"]}`). Because `max_tokens` was globally set to `6144`, the model spent **1,500+ tokens thinking** just to pick a section ID!
2. **Stage 4 (Clinical JSON Synthesis)**: Generates another 3,000+ tokens of thinking + criteria.

Combining both stages easily pushed total output tokens per query past **5k–6k tokens**, quickly consuming Groq rate limits.

---

### 3. Repetition Loops on Unconstrained Prompts
When instruct models are given an open 6k token window without a brevity constraint, they sometimes enter **repetition loops** (e.g., generating 60+ repeated criterion objects in a single list instead of grouping them into 2–4 concise clinical categories).

---

### How to Optimize & Control Token Usage

We can adjust the pipeline to use **targeted token limits per stage**:

1. **Stage 2 (Routing)**: Cap at **`max_tokens=300`** $\rightarrow$ Stops the model from overthinking routing decisions.
2. **Stage 4 (Synthesis)**: Set to **`max_tokens=2048`** with a `"Be concise and avoid repetitive bullets"` instruction $\rightarrow$ Produces the complete JSON report in ~700–900 tokens without wasting 3,000 tokens on thinking traces.
3. **Switch to non-reasoning fast models on Groq** (like `llama-3.1-8b-instant`), which do not output `<think>` blocks and generate only the clean JSON payload in ~400ms.

Would you like me to apply these stage-specific token caps to [`retrieval-hierarchical.py`](file:///home/vijaykumar/Desktop/project2/retrieval-hierarchical.py)?