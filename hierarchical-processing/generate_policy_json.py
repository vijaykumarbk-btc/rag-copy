"""
generate_policy_json.py
-----------------------
Generates a structured clinical prior-authorization policy summary JSON
matching the exact requested schema:
{
  "Prior auth required": "Yes",
  "Policy Name": "...",
  "Referred Sections": [...],
  "Medical necessity indications": [
    {
      "Guideline Category": "...",
      "Required findings": [...],
      "Source": "..."
    }
  ],
  "Non-Indications": [...],
  "Important criteria & exceptions": [...],
  "Documentation required": [...]
}

Integrates:
  - output/table.json (CPT Prior Auth lookup via cpt_table_lookup.py)
  - hierarchical-processing policy chunks & metadata
  - LLM synthesis with strict JSON formatting
"""

import os
import sys
import json
import re
from openai import OpenAI
from dotenv import load_dotenv

from cpt_table_lookup import CPTTableLookup

load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST")
CHAT_MODEL = os.getenv("CHAT_MODEL", "hf.co/unsloth/medgemma-1.5-4b-it-GGUF:Q8_0")

if not OLLAMA_HOST:
    raise ValueError("OLLAMA_HOST is not set in .env")

client = OpenAI(
    base_url=OLLAMA_HOST,
    api_key="ollama"
)

DEFAULT_METADATA_FILE = "/home/vijaykumar/Desktop/project2/hierarchical-processing/acdf_metadata.json"
DEFAULT_TABLE_JSON = "/home/vijaykumar/Desktop/project2/output/table.json"
DEFAULT_OUTPUT_JSON = "/home/vijaykumar/Desktop/project2/output/policy_summary_ACDF.json"


def clean_llm_json(raw_text: str) -> dict:
    """Extract and parse clean JSON from model output, handling thought tags and fences."""
    # Strip <thought> or <think> tags
    text = re.sub(r"<(?:thought|think)>.*?</(?:thought|think)>", "", raw_text, flags=re.DOTALL)
    # Strip leading thought text
    text = re.sub(r"^thought\s+.*?(?=(?:```|\{))", "", text, flags=re.DOTALL | re.IGNORECASE)

    # Search for JSON object {...}
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError(f"Could not find JSON object in LLM output: {raw_text[:300]}")

    json_str = match.group(0)
    return json.loads(json_str)


def collect_policy_context(metadata: list[dict], section_keywords: list[str]) -> str:
    """Collect text from chunks whose heading path or section matches keywords."""
    matching_chunks = []
    seen = set()

    for item in metadata:
        sec = item.get("section", "")
        heading_path = " ".join(item.get("heading_path", []))
        combined = f"{sec} {heading_path}".lower()

        if any(kw.lower() in combined for kw in section_keywords):
            cid = item.get("chunk_id")
            if cid not in seen:
                seen.add(cid)
                matching_chunks.append(item)

    # Sort in reading order
    matching_chunks.sort(key=lambda x: x.get("chunk_index", 0))

    formatted = []
    for c in matching_chunks:
        toc_id = c.get("toc_id", "")
        sec_title = c.get("section", "")
        text = c.get("text", "")
        formatted.append(f"### Section [{toc_id}] {sec_title}\n{text}")

    return "\n\n".join(formatted)


def generate_policy_summary(
    cpt_code: str = "22551",
    policy_name: str = "Cigna_ACDF_hierarchical",
    metadata_path: str = DEFAULT_METADATA_FILE,
    table_json_path: str = DEFAULT_TABLE_JSON,
    output_path: str = DEFAULT_OUTPUT_JSON
) -> dict:
    print("=" * 70)
    print(f"Generating Policy Summary for CPT: {cpt_code} | Policy: {policy_name}")
    print("=" * 70)

    # Step 1: Query Master Table for Prior Auth Status
    print(f"\n[Step 1] Querying master table ({table_json_path}) for CPT {cpt_code}...")
    cpt_lookup = CPTTableLookup(table_json_path)
    prior_auth_status = cpt_lookup.is_prior_auth_required([cpt_code])
    cpt_records = cpt_lookup.lookup_cpt(cpt_code)

    cpt_desc = cpt_records[0].get("CPT® Code Description") if cpt_records else "Spinal procedure"
    print(f"Prior Authorization Required: {prior_auth_status}")
    print(f"CPT Description: {cpt_desc}")

    # Step 2: Load Metadata Chunks
    print(f"\n[Step 2] Loading policy chunks from {metadata_path}...")
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    # Extract relevant policy sections: Initial Primary ACDF (CMM-601.4), Non-Indications (CMM-601.9), General Guidelines (CMM-601.1)
    relevant_keywords = [
        "CMM-601.4",
        "Radiculopathy",
        "Myelopathy",
        "CMM-601.9",
        "Non-Indications",
        "CMM-601.1",
        "General Guidelines",
        "Health Equity",
        "Instructions for use"
    ]
    context_text = collect_policy_context(metadata, relevant_keywords)
    print(f"Collected context length: {len(context_text)} characters.")

    # Step 3: Prompt LLM for Exact JSON Schema Synthesis
    print(f"\n[Step 3] Synthesizing policy criteria using {CHAT_MODEL}...")

    prompt = f"""You are an expert clinical medical policy analyst.
Based ONLY on the provided Medical Coverage Policy Context below, extract and generate a structured JSON document for procedure "{cpt_desc}" (CPT {cpt_code}).

### Medical Coverage Policy Context:
{context_text}

### Target Output JSON Schema:
Generate a JSON object with PRECISELY these top-level keys:
{{
  "Prior auth required": "{prior_auth_status}",
  "Policy Name": "{policy_name}",
  "Referred Sections": [
    "CMM-601.4: Initial Primary Anterior Cervical Discectomy and Fusion (ACDF)",
    "Radiculopathy",
    "Myelopathy"
  ],
  "Medical necessity indications": [
    {{
      "Guideline Category": "Radiculopathy",
      "Required findings": [
        "<Detailed bullet of symptom requirements, pain level, and functional impairment>",
        "<Unremitting radicular pain requirements>",
        "<Objective exam findings (dermatomal, motor, reflex, Spurling sign, etc.)>",
        "<Conservative therapy failure requirements (e.g. >=2 measures: medications >=6 weeks, PT/exercise >=6 weeks, injections)>",
        "<Plain cervical x-rays requirements with flexion/extension views>",
        "<MRI/CT imaging requirements showing neural compression>",
        "<Absence of unmanaged mental/behavioral health disorders>",
        "<Documented nicotine-free status requirements>"
      ],
      "Source": "CMM-601.4 Radiculopathy criteria (see policy text under 'Radiculopathy')."
    }},
    {{
      "Guideline Category": "Myelopathy",
      "Required findings": [
        "<Myelopathic symptoms requirements (weakness, numbness, fine motor, gait, bowel/bladder)>",
        "<Objective exam findings (grip-release, ataxic gait, hyperreflexia, Hoffmann, Babinski, clonus)>",
        "<MRI/CT imaging findings showing cord compression>",
        "<Absence of unmanaged mental/behavioral health disorders>",
        "<Documented nicotine-free status requirements>"
      ],
      "Source": "CMM-601.4 Myelopathy criteria (see policy text under 'Myelopathy')."
    }}
  ],
  "Non-Indications": [
    "<Bullet 1 from CMM-601.9: Not medically necessary / absence of required findings>",
    "<Bullet 2: Lack of objective imaging correlating with clinical findings>",
    "<Bullet 3: Failure to document adequate trial of conservative therapy>",
    "<Bullet 4: Presence of unmanaged major mental/behavioral health disorder>",
    "<Bullet 5: Current tobacco use without documented cessation >=6 weeks>"
  ],
  "Important criteria & exceptions": [
    "<Nicotine-free objective cotinine verification requirements and exceptions>",
    "<Mental/behavioral health disorder exclusions>",
    "<Conservative management trial duration and requirements>",
    "<Radiograph views specifications>"
  ],
  "Documentation required": [
    "<Clinical notes describing symptoms, functional limitations, duration>",
    "<Physical examination documentation with objective findings>",
    "<MRI/CT report confirming neural/cord compression>",
    "<Plain cervical spine x-ray reports with flexion/extension views>",
    "<Records of conservative management trial (meds, PT, injections)>",
    "<Cotinine test verification>",
    "<Mental health assessment verification>",
    "<Prior authorization request referencing CPT {cpt_code}>"
  ]
}}

### Instructions:
- Output ONLY valid, parseable JSON matching the exact structure above.
- Populate each array with comprehensive, factual details from the policy context.
- Do not output any preamble or extra text outside the JSON object.
"""

    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": "You are a clinical decision support system that outputs strictly valid JSON documents."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.0
    )

    raw_output = response.choices[0].message.content
    policy_json = clean_llm_json(raw_output)

    # Ensure Prior auth required and Policy Name match verified values
    policy_json["Prior auth required"] = prior_auth_status
    policy_json["Policy Name"] = policy_name

    # Step 4: Save & Validate Output
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(policy_json, f, indent=2, ensure_ascii=False)

    print(f"\n[Step 4] Successfully generated and saved policy summary to: {output_path}")
    print("\nGenerated JSON Preview:")
    print(json.dumps(policy_json, indent=2)[:1000] + "\n...")

    return policy_json


if __name__ == "__main__":
    cpt = sys.argv[1] if len(sys.argv) > 1 else "22551"
    pol = sys.argv[2] if len(sys.argv) > 2 else "Cigna_ACDF_hierarchical"
    generate_policy_summary(cpt_code=cpt, policy_name=pol)

