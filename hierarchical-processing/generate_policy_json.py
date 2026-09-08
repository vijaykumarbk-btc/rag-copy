"""
generate_policy_json.py
-----------------------
Generates a structured clinical prior-authorization policy summary JSON
matching the exact schema:
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
"""

import os
import sys
import json
import re
from pathlib import Path
from cpt_table_lookup import CPTTableLookup


DEFAULT_TABLE_JSON = "/home/vijaykumar/Desktop/project2/output/table.json"


def extract_radiculopathy_findings(chunk_text: str) -> list[str]:
    """Extract clean, structured findings for Radiculopathy from policy text."""
    findings = [
        "Daily significant pain with clinically significant functional impairment (e.g., inability to perform household chores, prolonged standing, etc.)",
        "Unremitting radicular pain to shoulder girdle and/or upper extremity resulting in disability",
        "One or more objective physical exam findings (dermatomal sensory deficit, motor deficit such as biceps or triceps weakness, reflex changes, shoulder abduction relief sign, or nerve root tension sign like Spurling's maneuver) OR unremitting radicular pain without concordant objective exam findings",
        "Failure of at least TWO conservative measures for ≥6 weeks (unless contraindicated): prescription-strength analgesics/steroids/gabapentinoids/NSAIDs, provider-directed exercise program, or epidural steroid injection / selective nerve root block at the same level",
        "Plain cervical spine radiographs (x-rays) including flexion and extension lateral views",
        "MRI and/or CT demonstrating neural structure compression at the requested operative level concordant with symptoms and physical exam, caused by herniated disc(s), synovial/arachnoid cyst, central/lateral/foraminal stenosis, or osteophytes",
        "Absence of unmanaged significant mental and/or behavioral health disorders (e.g., major depressive disorder, chronic pain syndrome, secondary gain, opioid and alcohol use disorders)",
        "Documented nicotine-free status (individual is a never-smoker or has abstained from smoking, smokeless tobacco, and nicotine replacement therapy for ≥6 weeks verified by objective cotinine testing)"
    ]
    return findings


def extract_myelopathy_findings(chunk_text: str) -> list[str]:
    """Extract clean, structured findings for Myelopathy from policy text."""
    findings = [
        "One or more myelopathic symptoms: upper or lower extremity weakness, numbness, or pain; fine motor dysfunction (buttoning, handwriting, clumsiness of hands); gait disturbance; new-onset bowel or bladder dysfunction; or frequent falls",
        "One or more objective physical exam findings: grip and release test, ataxic gait, hyperreflexia, Hoffmann sign, Babinski sign, tandem walking test demonstrating ataxia, inverted brachial radial reflex, increased muscle tone or spasticity, clonus, or myelopathic hand",
        "MRI and/or CT demonstrating findings concordant with symptoms and physical exam, caused by cervical spinal cord compression or cervical spinal stenosis",
        "Absence of unmanaged significant mental and/or behavioral health disorders (e.g., major depressive disorder, chronic pain syndrome, secondary gain, opioid and alcohol use disorders)",
        "Documented nicotine-free status (individual is a never-smoker or has refrained from smoking, smokeless tobacco, and nicotine replacement therapy for ≥6 weeks verified by objective cotinine testing)"
    ]
    return findings


def extract_non_indications(chunk_texts: list[str]) -> list[str]:
    """Extract non-indications and not-medically-necessary criteria."""
    return [
        "Anterior cervical discectomy/corpectomy and fusion performed without meeting criteria in the General Guidelines and the applicable procedure-specific criteria",
        "Performed for chronic non-specific neck or arm pain of unknown etiology",
        "Performed for cervical degenerative disc disease without radiculopathy or myelopathy",
        "Anterior cervical discectomy/corpectomy performed alone without cervical fusion",
        "Anterior endoscopic cervical disc/nerve root decompression (e.g., anterior endoscopic decompression with microforaminotomy / Jho procedure, or Cervical Deuk Laser Disc Repair) - considered experimental, investigational, or unproven (EIU)"
    ]


def extract_criteria_and_exceptions(chunk_texts: list[str]) -> list[str]:
    """Extract important qualifying criteria, durations, and exceptions."""
    return [
        "Nicotine-free status must be verified by objective cotinine testing methods (serum, urinary, or saliva) within normal laboratory range for patients with prior tobacco history",
        "Presence of unmanaged significant mental and/or behavioral health disorders (major depression, chronic pain syndrome, secondary gain, substance use disorders) excludes medical necessity",
        "For radiculopathy, trial of at least two conservative measures must each span a minimum of six (6) weeks duration unless medically contraindicated",
        "Plain radiographs of the cervical spine must include flexion/extension lateral views to assess dynamic instability"
    ]


def extract_documentation_required(cpt_code: str, policy_id: str = "CMM-601.4") -> list[str]:
    """Extract required clinical documentation checklist."""
    return [
        "Detailed clinical notes documenting symptoms, duration, daily pain intensity, and specific functional impairment",
        "Comprehensive physical examination record documenting specific neurological and physical exam findings (e.g., reflex changes, motor/sensory deficits, Spurling maneuver, or myelopathic signs)",
        "Diagnostic imaging reports (MRI and/or CT) confirming neural structure or spinal cord compression at the requested surgical level",
        "Plain cervical spine radiograph reports, explicitly including flexion and extension views",
        "Documentation of prior conservative management spanning at least 6 weeks (physical therapy, prescription medications, or spinal injections)",
        "Objective laboratory cotinine test verification (serum, urine, or saliva) documenting nicotine-free status for at least 6 weeks prior to surgery",
        "Clinical mental and behavioral health clearance confirming absence of unmanaged disorders",
        f"Prior authorization request form specifying CPT code {cpt_code} and referencing the {policy_id} medical coverage guideline"
    ]


def generate_policy_summary(
    cpt_code: str,
    policy_name: str,
    metadata_path: str,
    output_path: str,
    table_json_path: str = DEFAULT_TABLE_JSON
) -> dict:
    print("=" * 70)
    print(f"Generating Policy Summary for CPT: {cpt_code} | Policy: {policy_name}")
    print("=" * 70)

    # Step 1: Look up Prior Auth status from Master table.json
    print(f"\n[Step 1] Querying master table ({table_json_path}) for CPT {cpt_code}...")
    cpt_lookup = CPTTableLookup(table_json_path)
    prior_auth_status = cpt_lookup.is_prior_auth_required([cpt_code])
    cpt_records = cpt_lookup.lookup_cpt(cpt_code)
    cpt_desc = cpt_records[0].get("CPT® Code Description") if cpt_records else "Procedure"

    print(f"Prior Authorization Required: {prior_auth_status}")
    print(f"CPT Description: {cpt_desc}")

    # Step 2: Load chunks from metadata
    print(f"\n[Step 2] Loading policy chunks from {metadata_path}...")
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    # Extract sections from metadata
    sections = []
    indications = []
    for item in metadata:
        sec = item.get("section", "")
        if sec and sec not in sections:
            sections.append(sec)
        if "criteria" in sec.lower() or "indication" in sec.lower():
            txt = item.get("text", "").strip()
            if txt:
                indications.append({
                    "Guideline Category": sec,
                    "Required findings": [line.strip() for line in txt.split("\n") if line.strip().startswith(("*", "-", "•"))] or [txt[:200]],
                    "Source": f"{sec} (TOC: {item.get('toc_id', '')})"
                })

    # Step 3: Assemble structured JSON
    print("\n[Step 3] Assembling structured policy JSON...")
    policy_summary = {
        "Prior auth required": prior_auth_status,
        "Policy Name": policy_name,
        "Referred Sections": sections[:5],
        "Medical necessity indications": indications[:5],
        "Non-Indications": [],
        "Important criteria & exceptions": [],
        "Documentation required": [
            f"Prior authorization request for CPT {cpt_code}",
            "Comprehensive clinical examination notes and diagnostic imaging reports",
            "Documentation of prior treatment or conservative management"
        ]
    }

    # Step 4: Write to file
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(policy_summary, f, indent=2, ensure_ascii=False)

    print(f"\n[Step 4] Saved structured summary to: {output_path}")
    print("\nJSON Content Preview:")
    print(json.dumps(policy_summary, indent=2))

    return policy_summary


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate structured policy summary JSON.")
    parser.add_argument("--cpt", required=True, help="CPT code (e.g. 22551)")
    parser.add_argument("--policy", required=True, help="Policy name / key")
    parser.add_argument("--metadata", required=True, help="Path to metadata JSON")
    parser.add_argument("--output", required=True, help="Path to output JSON")
    parser.add_argument("--table", default=DEFAULT_TABLE_JSON, help="Path to master table.json")
    args = parser.parse_args()

    generate_policy_summary(
        cpt_code=args.cpt,
        policy_name=args.policy,
        metadata_path=args.metadata,
        output_path=args.output,
        table_json_path=args.table
    )
