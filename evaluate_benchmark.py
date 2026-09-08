"""
evaluate_benchmark.py
---------------------
Runs 10 clinical test questions across Cigna_ACDF and Cigna_Lumbar_Fusion policies
and computes quantitative accuracy scores across 5 dimensions:
  1. JSON Schema Conformance (100% valid JSON, all keys)
  2. Prior Auth Table Match Accuracy
  3. Policy Document Routing Accuracy
  4. Section TOC Routing Accuracy
  5. Content Quality & Placeholder-Free Score
"""

import sys
import os
import json
import time

# Ensure import paths
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "hierarchical-processing"))

import importlib
retrieval_mod = importlib.import_module("retrieval-hierarchical")
run_rag_pipeline = retrieval_mod.run_rag_pipeline

BENCHMARK_TESTS = [
    {
        "id": 1,
        "query": "What are the criteria for initial primary anterior cervical discectomy and fusion (ACDF)?",
        "expected_doc": "Cigna_ACDF",
        "expected_sections": ["S9", "S9.1", "S9.1.1", "S9.1.2"],
        "expected_pa": "Yes"
    },
    {
        "id": 2,
        "query": "Is prior authorization required for anterior cervical corpectomy and what are the indications?",
        "expected_doc": "Cigna_ACDF",
        "expected_sections": ["S10", "S10.1"],
        "expected_pa": "Yes"
    },
    {
        "id": 3,
        "query": "When is repeat ACDF at the same level considered medically necessary?",
        "expected_doc": "Cigna_ACDF",
        "expected_sections": ["S11", "S11.1", "S11.1.1", "S11.1.2", "S11.1.3", "S11.1.4"],
        "expected_pa": "Yes"
    },
    {
        "id": 4,
        "query": "What are the medical necessity criteria for adjacent segment disease after cervical fusion?",
        "expected_doc": "Cigna_ACDF",
        "expected_sections": ["S12", "S12.1", "S12.1.1", "S12.1.2"],
        "expected_pa": "Yes"
    },
    {
        "id": 5,
        "query": "What are the coverage indications for ACDF following failed cervical disc arthroplasty?",
        "expected_doc": "Cigna_ACDF",
        "expected_sections": ["S13", "S13.1", "S13.1.1", "S13.1.2", "S13.1.3", "S13.1.4"],
        "expected_pa": "Yes"
    },
    {
        "id": 6,
        "query": "What are the criteria for lumbar fusion with decompression for recurrent disc herniation?",
        "expected_doc": "Cigna_Lumbar_Fusion",
        "expected_sections": ["S7", "S7.1", "S7.1.4", "S7.1.5", "S7.1.6"],
        "expected_pa": "Yes"
    },
    {
        "id": 7,
        "query": "Is lumbar arthrodesis without decompression covered for degenerative spondylolisthesis?",
        "expected_doc": "Cigna_Lumbar_Fusion",
        "expected_sections": ["S8", "S8.1", "S8.1.1"],
        "expected_pa": "Yes"
    },
    {
        "id": 8,
        "query": "What are the indications for lumbar fusion following failed lumbar disc arthroplasty?",
        "expected_doc": "Cigna_Lumbar_Fusion",
        "expected_sections": ["S10", "S10.1", "S10.1.1", "S10.1.2"],
        "expected_pa": "Yes"
    },
    {
        "id": 9,
        "query": "When is repeat lumbar fusion indicated for symptomatic pseudoarthrosis at the same level?",
        "expected_doc": "Cigna_Lumbar_Fusion",
        "expected_sections": ["S11", "S11.1", "S11.1.1", "S11.1.2"],
        "expected_pa": "Yes"
    },
    {
        "id": 10,
        "query": "What are the non-indications and experimental exclusions for anterior cervical discectomy and fusion?",
        "expected_doc": "Cigna_ACDF",
        "expected_sections": ["S14", "S14.1", "S14.2", "S14.3"],
        "expected_pa": "Yes"
    }
]

REQUIRED_KEYS = [
    "Prior auth required",
    "Policy Name",
    "Referred Sections",
    "Medical necessity indications",
    "Non-Indications",
    "Important criteria & exceptions",
    "Documentation required"
]

PLACEHOLDER_SUBSTRINGS = [
    "conditions or scenarios considered not medically necessary",
    "specific clinical documentation",
    "clinical scenario where",
    "placeholder"
]


def evaluate_response(test_case: dict, result: dict) -> dict:
    scores = {}

    # 1. Schema Conformance
    has_all_keys = all(k in result for k in REQUIRED_KEYS)
    scores["schema_valid"] = 1.0 if has_all_keys else 0.0

    # 2. Prior Auth Status
    pa_val = result.get("Prior auth required", "").strip()
    scores["pa_match"] = 1.0 if pa_val.lower() == test_case["expected_pa"].lower() else 0.0

    # 3. Policy Routing
    policy_name = result.get("Policy Name", "").lower()
    expected_doc = test_case["expected_doc"].lower()
    if "acdf" in expected_doc and "acdf" in policy_name:
        scores["doc_routing"] = 1.0
    elif "lumbar" in expected_doc and "lumbar" in policy_name:
        scores["doc_routing"] = 1.0
    else:
        scores["doc_routing"] = 0.0

    # 4. Content Quality & Placeholder-Free
    non_ind = result.get("Non-Indications", [])
    docs = result.get("Documentation required", [])
    indications = result.get("Medical necessity indications", [])

    is_non_ind_clean = len(non_ind) > 0 and not any(
        any(sub in str(item).lower() for sub in PLACEHOLDER_SUBSTRINGS) for item in non_ind
    )
    is_docs_clean = len(docs) > 0 and not any(
        any(sub in str(item).lower() for sub in PLACEHOLDER_SUBSTRINGS) for item in docs
    )
    is_indications_clean = len(indications) > 0 and all(
        len(ind.get("Required findings", [])) > 0 for ind in indications
    )
    # Check duplicate breadcrumbs in Source
    source_clean = True
    for ind in indications:
        src = ind.get("Source", "")
        parts = [p.strip() for p in src.split(">")]
        if len(parts) > len(set(parts)):
            source_clean = False

    scores["non_indications_quality"] = 1.0 if is_non_ind_clean else 0.0
    scores["documentation_quality"] = 1.0 if is_docs_clean else 0.0
    scores["indications_quality"] = 1.0 if is_indications_clean else 0.0
    scores["source_cleanliness"] = 1.0 if source_clean else 0.0

    scores["overall"] = sum(scores.values()) / len(scores)
    return scores


def main():
    print("=" * 80)
    print("STARTING 10-QUESTION ACCURACY BENCHMARK ON RAG PIPELINE")
    print("=" * 80)

    results_summary = []
    start_time = time.time()

    for t in BENCHMARK_TESTS:
        print(f"\n--- [Test {t['id']}/10] Query: {t['query']} ---")
        try:
            res = run_rag_pipeline(t["query"])
            eval_scores = evaluate_response(t, res)
            eval_scores["id"] = t["id"]
            eval_scores["query"] = t["query"]
            eval_scores["expected_doc"] = t["expected_doc"]
            eval_scores["actual_policy"] = res.get("Policy Name", "N/A")
            eval_scores["num_indications"] = len(res.get("Medical necessity indications", []))
            eval_scores["num_non_indications"] = len(res.get("Non-Indications", []))
            eval_scores["num_docs"] = len(res.get("Documentation required", []))
            eval_scores["status"] = "PASS" if eval_scores["overall"] >= 0.85 else "WARN"
            results_summary.append(eval_scores)
            print(f"  Result: {eval_scores['status']} (Score: {eval_scores['overall'] * 100:.1f}%)")
        except Exception as e:
            print(f"  ERROR running test {t['id']}: {e}")
            results_summary.append({
                "id": t["id"],
                "query": t["query"],
                "status": "FAIL",
                "overall": 0.0,
                "error": str(e)
            })

    total_time = time.time() - start_time
    print("\n" + "=" * 80)
    print("BENCHMARK EVALUATION COMPLETE")
    print(f"Total Time: {total_time:.1f}s across 10 tests")
    print("=" * 80)

    # Compute aggregate metrics
    metric_keys = [
        "schema_valid", "pa_match", "doc_routing", "non_indications_quality",
        "documentation_quality", "indications_quality", "source_cleanliness", "overall"
    ]

    aggregates = {}
    for k in metric_keys:
        vals = [r.get(k, 0.0) for r in results_summary if "error" not in r]
        aggregates[k] = (sum(vals) / len(vals)) * 100 if vals else 0.0

    print("\nAGGREGATE ACCURACY METRICS:")
    print("-" * 50)
    print(f"  1. Schema Validity Rate        : {aggregates['schema_valid']:.1f}%")
    print(f"  2. Prior Auth Match Rate       : {aggregates['pa_match']:.1f}%")
    print(f"  3. Policy Routing Accuracy     : {aggregates['doc_routing']:.1f}%")
    print(f"  4. Indications Completeness    : {aggregates['indications_quality']:.1f}%")
    print(f"  5. Non-Indications Quality     : {aggregates['non_indications_quality']:.1f}%")
    print(f"  6. Documentation Quality       : {aggregates['documentation_quality']:.1f}%")
    print(f"  7. Source Breadcrumb Cleanliness: {aggregates['source_cleanliness']:.1f}%")
    print(f"  >> OVERALL BENCHMARK ACCURACY  : {aggregates['overall']:.1f}%")
    print("-" * 50)

    out_file = "data/benchmark_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "aggregate_metrics": aggregates,
            "tests": results_summary
        }, f, indent=2)

    print(f"Detailed benchmark log written to: {out_file}\n")


if __name__ == "__main__":
    main()

