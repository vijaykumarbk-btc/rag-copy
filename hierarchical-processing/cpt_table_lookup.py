"""
cpt_table_lookup.py
-------------------
Utility to look up CPT codes and procedure categories in output/table.json
to determine whether commercial prior authorization is required.
Supports:
  1. Exact CPT/HCPCS code lookup (e.g. '22551', '22612')
  2. Natural language keyword search against procedure descriptions without hardcoding
"""

import os
import sys
import json
import re
from pathlib import Path


class CPTTableLookup:
    def __init__(self, table_json_path: str = None):
        if table_json_path is None:
            table_json_path = str(Path(__file__).resolve().parent.parent / "output" / "table.json")
        self.table_json_path = table_json_path
        self._data = None
        self._cpt_index = {}
        self._rows = []
        self._load()

    def _load(self):
        if not os.path.exists(self.table_json_path):
            return

        with open(self.table_json_path, "r", encoding="utf-8") as f:
            self._data = json.load(f)

        tables = self._data.get("tables", [])
        for table in tables:
            for row in table.get("rows", []):
                self._rows.append(row)
                raw_code = str(row.get("CPT® Code", "")).strip()
                if not raw_code:
                    continue

                codes = re.findall(r"[0-9A-Za-z]+", raw_code)
                for code in codes:
                    if code not in self._cpt_index:
                        self._cpt_index[code] = []
                    self._cpt_index[code].append(row)

    def lookup_cpt(self, cpt_code: str) -> list[dict]:
        clean_code = re.sub(r"[^\w]", "", str(cpt_code).strip())
        return self._cpt_index.get(clean_code, [])

    def search_by_query(self, query: str, max_results: int = 5) -> list[dict]:
        """Search table.json rows using words in query against CPT description and code."""
        # 1. Check for explicit CPT / HCPCS codes in query (any standard 5-character format)
        explicit_codes = re.findall(r"\b[0-9]{4}[0-9A-Za-z]\b|\b[0-9]{5}\b", query)
        matches = []
        seen = set()

        for c in explicit_codes:
            for r in self.lookup_cpt(c):
                code = r.get("CPT® Code")
                if code not in seen:
                    seen.add(code)
                    matches.append(r)

        if explicit_codes:
            return matches[:max_results]

        # 2. Extract meaningful search terms from query without conversational filler words
        STOP_WORDS = {
            "what", "are", "the", "for", "is", "of", "to", "in", "and", "or", "a", "an",
            "due", "when", "criteria", "indications", "medical", "necessity", "considered",
            "with", "does", "require", "required", "prior", "auth", "authorization", "how",
            "all", "each", "by", "from", "at", "if", "yes", "give", "documents", "document",
            "please", "tell", "about", "show", "can", "you", "would", "like", "know",
            "under", "status", "policy"
        }
        raw_words = re.findall(r"[a-z0-9]+", query.lower())
        # Filter stop words, short words, and 1-4 digit numbers (e.g. policy/chapter IDs) while preserving 5-digit CPT codes
        meaningful_keywords = [
            w for w in raw_words 
            if w not in STOP_WORDS and len(w) >= 3 and not (w.isdigit() and len(w) < 5)
        ]

        if not meaningful_keywords:
            meaningful_keywords = [w for w in raw_words if len(w) >= 3 and not (w.isdigit() and len(w) < 5)]

        scored_rows = []
        for r in self._rows:
            desc = str(r.get("CPT® Code Description", "")).lower()
            code = str(r.get("CPT® Code", "")).lower()

            score = 0
            for kw in meaningful_keywords:
                if len(kw) == 5 and kw in code:
                    score += 5  # Strong match on CPT code
                elif len(kw) >= 3 and kw in desc:
                    score += 2  # Match on description

            if score > 0:
                scored_rows.append((score, r))

        scored_rows.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored_rows[:max_results]]

    def is_prior_auth_required(self, cpt_codes: list[str]) -> str:
        results = []
        for code in cpt_codes:
            matches = self.lookup_cpt(code)
            for m in matches:
                pa_val = m.get("Commercial Prior Authorization Required?", "")
                if pa_val:
                    results.append(pa_val.strip())

        if any("yes" in r.lower() for r in results):
            return "Yes"
        elif any("add on" in r.lower() for r in results):
            return "Add On"
        elif any("none" in r.lower() or "no" in r.lower() for r in results):
            return "No"
        return "Unknown"

    def analyze_query_prior_auth(self, query: str) -> dict:
        """Analyze query against table.json to get prior auth status and candidate CPTs."""
        matches = self.search_by_query(query)
        if not matches:
            return {
                "prior_auth_required": "No",
                "matched_cpts": [],
                "primary_description": ""
            }

        cpts = []
        statuses = []
        for m in matches:
            raw_code = str(m.get("CPT® Code", "")).strip()
            codes = re.findall(r"[0-9A-Za-z]+", raw_code)
            cpts.extend(codes)
            st = m.get("Commercial Prior Authorization Required?")
            if st is not None and str(st).strip():
                statuses.append(str(st).strip())
            else:
                statuses.append("No")

        if any("yes" in s.lower() for s in statuses):
            pa = "Yes"
        elif any("add on" in s.lower() for s in statuses):
            pa = "Add On"
        elif any("no" in s.lower() or "none" in s.lower() for s in statuses):
            pa = "No"
        else:
            pa = statuses[0] if statuses else "No"
        first_desc = matches[0].get("CPT® Code Description", "")

        return {
            "prior_auth_required": pa,
            "matched_cpts": list(set(cpts)),
            "primary_description": first_desc,
            "matched_rows": matches
        }


if __name__ == "__main__":
    lookup = CPTTableLookup()
    print("CPT Index size:", len(lookup._cpt_index))
    print("Test lookup 22551:", len(lookup.lookup_cpt("22551")))
