"""
retrieval-hierarchical.py
-------------------------
Multi-Document TOC-Guided Hierarchical RAG Pipeline.

Pipeline Flow:
  Stage 1: Master Table Check (output/table.json)
    Matches user query to procedure CPT codes and determines: "Prior auth required": "Yes" / "No".
  Stage 2: Table of Contents (TOC) Multi-Document Routing
    Routes user query against available policy TOCs to identify the target document and specific toc_id(s).
  Stage 3: Scoped Hybrid Retrieval
    Runs BM25 + Semantic dense embeddings strictly over candidate chunks matching the routed toc_id(s),
    with automatic sibling condition completion.
  Stage 4: Structured Clinical JSON Synthesis
    Synthesizes the retrieved criteria and master table status into the exact JSON schema requested.
"""

import os
import sys
import json
import re
from datetime import datetime
from dotenv import load_dotenv

# Include hierarchical-processing in path for modules
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HP_DIR = os.path.join(BASE_DIR, "hierarchical-processing")
if HP_DIR not in sys.path:
    sys.path.append(HP_DIR)

from document_registry import DocumentRegistry
from cpt_table_lookup import CPTTableLookup
from hybrid_search_hierarchical import scoped_search, search

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEN_MODEL = os.getenv("GEN_MODEL", "groq/compound-mini")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://192.168.0.33:11434/v1")
OLLAMA_MODEL = os.getenv("CHAT_MODEL", "hf.co/unsloth/medgemma-1.5-4b-it-GGUF:Q8_0")

OUTPUT_DIR = os.path.join(BASE_DIR, "data", "results_new")
TABLE_JSON_PATH = os.path.join(BASE_DIR, "output", "table.json")

# Initialize shared registry and CPT lookup
registry = DocumentRegistry(base_dir=HP_DIR)
cpt_lookup = CPTTableLookup(table_json_path=TABLE_JSON_PATH)


# ============================================================
# LLM CALL WITH ROBUST PROVIDER HANDLING
# ============================================================

def call_llm(prompt: str, json_mode: bool = True) -> str:
    """Call Groq API with automatic fallback to local Ollama if rate-limited or unavailable."""
    if GROQ_API_KEY:
        try:
            from groq import Groq
            groq_client = Groq(api_key=GROQ_API_KEY)
            models_to_try = [GEN_MODEL, "llama-3.1-8b-instant", "groq/compound-mini", "openai/gpt-oss-120b"]
            for m in models_to_try:
                if not m:
                    continue
                # Try with json_mode first, then without if Groq rejects the JSON
                for use_json in ([True, False] if json_mode else [False]):
                    try:
                        kwargs = {
                            "model": m,
                            "messages": [
                                {"role": "system", "content": "You are a clinical decision support assistant that outputs strictly valid JSON objects without preamble."},
                                {"role": "user", "content": prompt}
                            ],
                            "temperature": 0.1,
                            "max_tokens": 5000
                        }
                        if use_json:
                            kwargs["response_format"] = {"type": "json_object"}
                        response = groq_client.chat.completions.create(**kwargs)
                        content = response.choices[0].message.content.strip()
                        if content:
                            return content
                    except Exception as m_err:
                        err_str = str(m_err).lower()
                        # Rate limit → try next model
                        if "429" in str(m_err) or "rate_limit" in err_str:
                            break
                        # Groq's JSON validator rejected the output → retry same model without json_mode
                        if "json_validate_failed" in err_str or "failed to validate json" in err_str:
                            continue
                        # Model not found or not supported → try next model
                        if "model_not_found" in err_str or "not found" in err_str or "not_supported" in err_str:
                            break
                        # Unknown error → try next model
                        break
        except Exception as e:
            pass  # Fall through to local Ollama

    from openai import OpenAI
    ollama_client = OpenAI(base_url=OLLAMA_HOST, api_key="ollama")
    response = ollama_client.chat.completions.create(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": "You are a clinical decision support assistant that outputs strictly valid JSON objects without preamble."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1,
        max_tokens=5000
    )
    return response.choices[0].message.content.strip()


try:
    import json_repair
except ImportError:
    json_repair = None


def extract_clean_json(raw_text: str) -> dict:
    """Extract and clean JSON object from LLM response, handling reasoning models and truncated thinking tags."""
    if not raw_text or not raw_text.strip():
        raise ValueError("Empty LLM response received")

    # 1. Strip closed reasoning / thinking tags
    text = re.sub(r"<(?:thought|think)>.*?</(?:thought|think)>", "", raw_text, flags=re.DOTALL)
    text = re.sub(r"^thought\s+.*?(?=(?:```|\{))", "", text, flags=re.DOTALL | re.IGNORECASE)

    # 2. If <think> or <thought> was left unclosed (due to token limit/formatting), extract from the first '{'
    first_brace = text.find("{")
    if first_brace == -1:
        # Check in raw_text in case it was inside the thinking tag
        first_brace = raw_text.find("{")
        if first_brace != -1:
            text = raw_text[first_brace:]
    else:
        text = text[first_brace:]

    # 3. Extract outermost JSON block if closing brace exists
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    candidate = match.group(0).strip() if match else text.strip()

    # 4. Direct standard parse attempt
    try:
        return json.loads(candidate)
    except Exception:
        pass

    # 5. Remove trailing commas before closing braces/brackets
    cleaned_no_trailing = re.sub(r",\s*([\]}])", r"\1", candidate)
    try:
        return json.loads(cleaned_no_trailing)
    except Exception:
        pass

    # 6. Use json_repair (repairs unclosed braces, truncated JSON, and quote issues)
    if json_repair is not None:
        try:
            repaired = json_repair.loads(candidate)
            if isinstance(repaired, dict):
                return repaired
        except Exception:
            pass

        try:
            repaired = json_repair.loads(raw_text)
            if isinstance(repaired, dict):
                return repaired
        except Exception:
            pass

    # 7. Fallback: try to repair trailing text
    if not candidate.endswith("}"):
        candidate_closed = candidate + "\n}"
        try:
            return json.loads(re.sub(r",\s*([\]}])", r"\1", candidate_closed))
        except Exception:
            pass

    raise ValueError(f"Could not find valid JSON object in output: {raw_text[:200]}")


# ============================================================
# STAGE 1: MASTER TABLE PRIOR AUTH CHECK
# ============================================================

def check_master_table_prior_auth(query: str) -> dict:
    """
    Stage 1: Check output/table.json for procedure matching the query.
    Returns: prior_auth_required ('Yes'/'No'), matched_cpts, and description.
    """
    analysis = cpt_lookup.analyze_query_prior_auth(query)
    return analysis


# ============================================================
# STAGE 2: MULTI-DOCUMENT TOC ROUTING
# ============================================================

def route_query_to_toc(query: str) -> tuple[str, list[str]]:
    """
    Stage 2: Route user query against available policy Table of Contents using LLM.
    Returns: (document_key, list_of_toc_ids)
    """
    compact_tocs = registry.get_compact_tocs()
    doc_keys_str = ", ".join(f'"{k}"' for k in registry.documents.keys())

    prompt = f"""Given the following clinical coverage policies Table of Contents and a clinical question, identify:
1. The most relevant document key (one of: {doc_keys_str}). If NONE of the policies cover or are relevant to the question, set "document_key": null and "toc_ids": [].
2. The specific section ID(s) (e.g. ["S9", "S9.1", "S9.1.1", "S9.1.2"] or ["S7.1.5"])

### Documents & Table of Contents:
{compact_tocs}

### Question:
{query}

### Output Instructions:
Output strictly a JSON object with keys "document_key" and "toc_ids":
{{"document_key": "...", "toc_ids": ["S..."]}}
"""

    try:
        raw_resp = call_llm(prompt, json_mode=True)
        routing_data = extract_clean_json(raw_resp)
        doc_key = routing_data.get("document_key")
        toc_ids = routing_data.get("toc_ids", [])
        if doc_key in registry.documents:
            valid_ids = [str(x).strip() for x in toc_ids if re.match(r"^S\d+(?:\.\d+)*$", str(x).strip())]
            return doc_key, valid_ids
    except Exception as e:
        print(f"[Notice] TOC routing exception ({e})")

    return None, []


# ============================================================
# STAGE 3: SCOPED HYBRID RETRIEVAL
# ============================================================

def retrieve_scoped_chunks(query: str, doc_key: str, candidate_toc_ids: list[str], top_k: int = 8) -> list[dict]:
    """
    Stage 3: Run hybrid search strictly scoped to the candidate toc_ids of the target document.
    """
    results = scoped_search(
        query=query,
        policy_hint=doc_key,
        candidate_toc_ids=candidate_toc_ids,
        top_k=top_k,
        alpha=0.5,
        mode="hybrid"
    )
    return results


def clean_section_breadcrumb(section_path: str) -> str:
    """Deduplicate repeated adjacent segments in breadcrumb hierarchies."""
    if not section_path:
        return ""
    parts = [p.strip() for p in section_path.split(">") if p.strip()]
    deduped = []
    for p in parts:
        if not deduped:
            deduped.append(p)
        else:
            prev = deduped[-1].lower()
            curr = p.lower()
            if curr == prev or curr.startswith(prev) or prev.startswith(curr):
                if len(p) > len(deduped[-1]):
                    deduped[-1] = p
            else:
                deduped.append(p)
    return " > ".join(deduped)


def build_context(results: list[dict]) -> str:
    blocks = []
    for i, result in enumerate(results):
        sec = clean_section_breadcrumb(result.get('section', ''))
        t_id = result.get('toc_id', '')
        header = f"[{i + 1}] Section: {sec}" + (f" (TOC: {t_id})" if t_id else "")
        blocks.append(f"{header}\n{result.get('text', '')}")
    return "\n\n---\n\n".join(blocks)


# ============================================================
# STAGE 4: STRUCTURED CLINICAL SYNTHESIS
# ============================================================

def build_synthesis_prompt(query: str, context: str, prior_auth_status: str, policy_name: str) -> str:
    return f"""You are an expert clinical medical policy analyst.
Analyze the user's clinical question and the provided policy context below.
Synthesize the requirements into a comprehensive, high-precision clinical policy report.

You must format your answer strictly as a valid JSON object matching this schema:

{{
  "Prior auth required": "{prior_auth_status}",
  "Policy Name": "{policy_name}",
  "Referred Sections": [
    "<Primary policy section ID/title>",
    "<Clinical condition / subsection 1>",
    "<Clinical condition / subsection 2>"
  ],
  "Medical necessity indications": [
    {{
      "Guideline Category": "<Clinical Condition / Category Name>",
      "Required findings": [
        "<Detailed bullet of symptom requirements, severity, and functional impairment>",
        "<Detailed bullet of objective physical examination findings required>",
        "<Detailed bullet of diagnostic imaging / laboratory findings required>",
        "<Detailed bullet of conservative management requirements and trial duration>",
        "<Detailed bullet of general criteria: qualifying rules and behavioral/risk health criteria>"
      ],
      "Source": "<Clean section citation without repeating titles, e.g. Section Title > Subsection (TOC: ID)>"
    }}
  ],
  "Non-Indications": [
    "<Clinical scenario where procedure is NOT medically necessary or is excluded based on policy rules (e.g. surgery prior to required elapsed interval, absence of concordant objective imaging or clinical deficits, failure to complete required trial of conservative therapy, unmanaged behavioral/risk health disorders)>"
    "<List clinical scenarios where the procedure is NOT medically necessary or is excluded based on the policy context. If none mentioned in context, output []>"
  ],
  "Important criteria & exceptions": [
    "<Important qualifying rules, verification methods, conservative care exceptions, or multi-level / concurrent procedure requirements>"
    "<List qualifying rules, verification methods, or exceptions stated in the policy context. If none, output []>"
  ],
  "Documentation required": [
    "<Specific clinical documents, diagnostic imaging reports, pathology/laboratory results, and provider notes required to verify criteria based strictly on the context>"
    "<List specific clinical documents, imaging reports, or provider records required to verify criteria based on the context. If none required or mentioned, output []>"
  ]
}}

### Medical Policy Context:
{context}

### User Question:
{query}

### CRITICAL OUTPUT INSTRUCTIONS:
1. Output ONLY a valid JSON object. Do not include markdown code blocks or conversational text.
2. NO PLACEHOLDERS OR GENERIC TEXT: Do NOT output placeholder text like "Conditions or scenarios considered not medically necessary" or "Specific clinical documentation, imaging reports, or test results required for submission".
3. "Documentation required": You MUST derive and list every concrete clinical document (imaging views, prior operative reports, therapy records, laboratory results) needed to prove the patient meets the criteria in the context.
4. "Non-Indications": You MUST extract or derive the specific clinical scenarios where the procedure is NOT medically necessary or is excluded based on the policy criteria.
5. "Source": Clean breadcrumbs only. Do not duplicate titles (e.g., write "Section Title > Subsection", NEVER "Section Title... > Section Title...").
6. Ground all answers strictly in the provided Medical Policy Context. Do NOT invent criteria or use generic placeholder text.
7. If "Documentation required" or "Non-Indications" are not specified or required in the context, return an empty array [] for that field.
"""


def run_rag_pipeline(query: str, top_k: int = 8) -> dict:
    print("=" * 70)
    print(f"QUERY: {query}")
    print("=" * 70)

    # ---------------------------------------------------------
    # STAGE 1: Master Table Check
    # ---------------------------------------------------------
    print("\n[Stage 1: Master Table Check]")
    table_analysis = check_master_table_prior_auth(query)
    prior_auth_status = table_analysis.get("prior_auth_required", "Yes")
    matched_cpts = table_analysis.get("matched_cpts", [])
    cpt_desc = table_analysis.get("primary_description", "")
    print(f"  Prior Authorization Required: {prior_auth_status}")
    print(f"  Matched CPT Codes           : {matched_cpts}")
    if cpt_desc:
        print(f"  Procedure Description       : {cpt_desc[:80]}...")

    # ---------------------------------------------------------
    # STAGE 2: TOC-Level Policy & Section Routing
    # ---------------------------------------------------------
    print("\n[Stage 2: TOC-Level Routing]")
    doc_key, routed_toc_ids = route_query_to_toc(query)

    if not doc_key or doc_key not in registry.documents:
        print("  [Notice] No matching policy document identified in registry.")
        structured_json = {
            "Prior auth required": prior_auth_status,
            "Policy Name": "None Identified",
            "Referred Sections": [],
            "Medical necessity indications": [],
            "Non-Indications": [],
            "Important criteria & exceptions": [],
            "Documentation required": [],
            "Notice": f"No registered medical coverage policy was identified that covers the clinical question: '{query}'."
        }
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = "".join(c if c.isalnum() or c == " " else "" for c in query)
        slug = "_".join(slug.split())[:50]
        filename = f"{timestamp}_{slug}.json"
        filepath = os.path.join(OUTPUT_DIR, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(structured_json, f, indent=2, ensure_ascii=False)
        print(f"\nReport successfully saved to: {filepath}")
        print("\n" + "=" * 70)
        print("FINAL STRUCTURED JSON OUTPUT:")
        print("=" * 70)
        print(json.dumps(structured_json, indent=2))
        print("=" * 70)
        return structured_json

    doc_info = registry.get_document(doc_key)
    policy_name = doc_info["display_name"] if doc_info else doc_key
    print(f"  Target Policy Document: {doc_key} ({policy_name})")
    print(f"  Routed Section IDs    : {routed_toc_ids}")

    # ---------------------------------------------------------
    # STAGE 3: Scoped Hybrid Retrieval
    # ---------------------------------------------------------
    print("\n[Stage 3: Scoped Hybrid Search (BM25 + Dense)]")
    results = retrieve_scoped_chunks(
        query=query,
        doc_key=doc_key,
        candidate_toc_ids=routed_toc_ids,
        top_k=top_k
    )
    print(f"  Retrieved {len(results)} scoped chunks (with condition completion):")
    for i, r in enumerate(results[:5], 1):
        print(f"    {i}. [{r.get('toc_id', 'N/A')}] {r.get('section', '')[:65]}")

    if not results:
        print(f"  [Notice] No retrievable content found in routed sections {routed_toc_ids} of {doc_key}.")
        structured_json = {
            "Prior auth required": prior_auth_status,
            "Policy Name": policy_name,
            "Referred Sections": routed_toc_ids,
            "Medical necessity indications": [],
            "Non-Indications": [],
            "Important criteria & exceptions": [],
            "Documentation required": [],
            "Notice": f"The routed section(s) {routed_toc_ids} in policy '{policy_name}' do not contain clinical coverage criteria."
        }
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = "".join(c if c.isalnum() or c == " " else "" for c in query)
        slug = "_".join(slug.split())[:50]
        filename = f"{timestamp}_{slug}.json"
        filepath = os.path.join(OUTPUT_DIR, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(structured_json, f, indent=2, ensure_ascii=False)
        print(f"\nReport successfully saved to: {filepath}")
        print("\n" + "=" * 70)
        print("FINAL STRUCTURED JSON OUTPUT:")
        print("=" * 70)
        print(json.dumps(structured_json, indent=2))
        print("=" * 70)
        return structured_json

    # ---------------------------------------------------------
    # STAGE 4: Structured Clinical JSON Synthesis
    # ---------------------------------------------------------
    print("\n[Stage 4: Structured Clinical JSON Synthesis]")
    context = build_context(results)
    prompt = build_synthesis_prompt(
        query=query,
        context=context,
        prior_auth_status=prior_auth_status,
        policy_name=policy_name
    )

    raw_response = call_llm(prompt, json_mode=True)
    structured_json = extract_clean_json(raw_response)

    # Ensure required fields conform
    structured_json["Prior auth required"] = prior_auth_status
    if "Policy Name" not in structured_json or not structured_json["Policy Name"]:
        structured_json["Policy Name"] = policy_name

    # Schema key normalization
    if "Medical necessity indications" not in structured_json:
        if "criteria" in structured_json and isinstance(structured_json["criteria"], list):
            indications = []
            for c in structured_json["criteria"]:
                if isinstance(c, dict):
                    desc = c.get("description", "")
                    docs = c.get("documentation_required", [])
                    indications.append({
                        "Guideline Category": desc[:60] if desc else "Clinical Criteria",
                        "Required findings": [desc] + (docs if isinstance(docs, list) else []),
                        "Source": policy_name
                    })
            structured_json["Medical necessity indications"] = indications
        else:
            structured_json["Medical necessity indications"] = []

    if "Referred Sections" not in structured_json or not structured_json["Referred Sections"]:
        structured_json["Referred Sections"] = [policy_name]

    if "Important criteria & exceptions" not in structured_json:
        structured_json["Important criteria & exceptions"] = []

    # Post-process: clean breadcrumbs in Source and Referred Sections
    for ind in structured_json.get("Medical necessity indications", []):
        if "Source" in ind and isinstance(ind["Source"], str):
            ind["Source"] = clean_section_breadcrumb(ind["Source"])

    if "Referred Sections" in structured_json and isinstance(structured_json["Referred Sections"], list):
        cleaned_refs = []
        for ref in structured_json["Referred Sections"]:
            c = clean_section_breadcrumb(ref)
            if c and c not in cleaned_refs:
                cleaned_refs.append(c)
        structured_json["Referred Sections"] = cleaned_refs

    # Strip any echoed placeholder text
    PLACEHOLDER_SUBSTRINGS = [
        "conditions or scenarios considered not medically necessary",
        "specific clinical documentation, imaging reports",
        "clinical scenario where",
        "condition category name"
    ]
    if "Non-Indications" in structured_json and isinstance(structured_json["Non-Indications"], list):
        structured_json["Non-Indications"] = [
            item for item in structured_json["Non-Indications"]
            if not any(sub in str(item).lower() for sub in PLACEHOLDER_SUBSTRINGS)
        ]
    elif "Non-Indications" not in structured_json:
        structured_json["Non-Indications"] = []

    if "Documentation required" in structured_json and isinstance(structured_json["Documentation required"], list):
        structured_json["Documentation required"] = [
            item for item in structured_json["Documentation required"]
            if not any(sub in str(item).lower() for sub in PLACEHOLDER_SUBSTRINGS)
        ]
    elif "Documentation required" not in structured_json:
        structured_json["Documentation required"] = []


    # Save output to data/results_new
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = "".join(c if c.isalnum() or c == " " else "" for c in query)
    slug = "_".join(slug.split())[:50]
    filename = f"{timestamp}_{slug}.json"
    filepath = os.path.join(OUTPUT_DIR, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(structured_json, f, indent=2, ensure_ascii=False)

    print(f"\nReport successfully saved to: {filepath}")
    print("\n" + "=" * 70)
    print("FINAL STRUCTURED JSON OUTPUT:")
    print("=" * 70)
    print(json.dumps(structured_json, indent=2))
    print("=" * 70)

    return structured_json


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    if len(sys.argv) > 1:
        user_query = " ".join(sys.argv[1:])
    else:
        user_query = input("Enter your query: ")

    run_rag_pipeline(user_query)