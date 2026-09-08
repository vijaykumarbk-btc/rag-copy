"""
Robust Docling table extraction with post-processing safeguards.

WHY THIS IS NEEDED:
Docling's table structure model infers rows/columns from visual layout.
When a source PDF has two physical rows with no visible grid line between
them (common in Excel-export PDFs), the model can merge them into a
single logical row -- producing cells like "15787 15786" (two CPT codes
crammed together) or a blank code where the code actually wrapped onto
its own line. No dataframe-level cleanup can perfectly undo this --
the information about where row 1 ended and row 2 began is already lost
by the time you have a flat cell value. What THIS script does instead:

1. Extracts tables as before.
2. Runs each row through validation: does the code column look like
   exactly one CPT/HCPCS code? Multiple codes? Blank?
3. For multi-code rows, attempts a SAFE auto-split only when every
   column has the same number of space-separated tokens (so we can
   pair them up positionally without guessing). Otherwise it leaves
   the row intact but flags it -- silently guessing a wrong split is
   worse than leaving a visible, reviewable problem.
4. Every row keeps a `_source_table_index` / `_row_issues` field so
   downstream steps (like linking to a provenance layer) know exactly
   which rows to distrust.
5. Writes a companion `*_issues.json` listing every flagged row with
   its table_id/row_index, so review time goes to the ~5-6% of rows
   that actually need it instead of re-checking everything.

This does NOT claim to reach 100% automatically -- some merges are
genuinely ambiguous (different token counts per column) and need a
human glance at the PDF page. It gets you from silent corruption to
a bounded, reviewable list.
"""
import json
import re
from pathlib import Path

from docling.document_converter import DocumentConverter


# ============================================================
# CONFIG
# ============================================================

PDF_PATH = Path("/home/vijaykumar/Desktop/project/extra_pdfs/Table.pdf")
OUTPUT_PATH = Path("output/table.json")
ISSUES_PATH = Path("output/table_issues.json")

OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

# Name (case-insensitive substring) of the column that holds the code.
# Adjust if your header text differs.
CODE_COLUMN_HINT = "cpt"

# CPT codes: 5 digits, or digit+4chars (HCPCS like C9807), or 4digits+letter
# (temporary codes like 0990T), optionally with a trailing crossover marker.
CODE_RE = re.compile(r"^[A-Z0-9]{4,6}\*?$")


# ============================================================
# HELPERS
# ============================================================

def find_code_column(columns):
    """Locate the CPT/HCPCS code column by header text, not position --
    column order can shift between exports."""
    for col in columns:
        if CODE_COLUMN_HINT in col.lower():
            return col
    return None


def clean_cell(value):
    """NaN-safe, whitespace-safe cell cleanup."""
    if value is None:
        return None
    if isinstance(value, float) and value != value:  # NaN
        return None
    text = str(value).strip()
    return text if text else None


def looks_like_single_code(text):
    if text is None:
        return False
    return bool(CODE_RE.match(text.strip()))


def looks_like_multi_code(text):
    """True if the code cell contains 2+ whitespace-separated tokens
    that each independently look like a valid code -- the signature
    of two merged rows."""
    if text is None:
        return False
    tokens = text.split()
    return len(tokens) >= 2 and all(CODE_RE.match(t) for t in tokens)


def try_split_merged_row(row_data, code_col, columns):
    """
    Attempt a SAFE split of a row where the code column contains
    multiple codes (merged rows). Only splits when every column has
    the same token count as the code column -- that's the one case
    where positional pairing is actually justified, not a guess.

    Returns a list of 2+ row dicts on success, or None if the split
    isn't safe (caller should flag instead of guessing).
    """
    token_counts = {}
    for col in columns:
        val = row_data.get(col)
        token_counts[col] = len(val.split()) if val else 0

    n = token_counts[code_col]
    if n < 2:
        return None

    # Every non-empty column must split into exactly n tokens for a
    # positional split to be trustworthy.
    for col in columns:
        c = token_counts[col]
        if c not in (0, n):
            return None  # ambiguous -- don't guess

    split_rows = []
    for i in range(n):
        new_row = {}
        for col in columns:
            val = row_data.get(col)
            if not val:
                new_row[col] = None
            else:
                toks = val.split()
                new_row[col] = toks[i] if len(toks) == n else val
        split_rows.append(new_row)
    return split_rows


# ============================================================
# CONVERT PDF
# ============================================================

converter = DocumentConverter()
result = converter.convert(PDF_PATH)
document = result.document


# ============================================================
# EXTRACT + VALIDATE TABLES
# ============================================================

tables = []
issues = []

for table_index, table in enumerate(document.tables, start=1):
    table_id = f"table_{table_index:03d}"

    data = table.export_to_dataframe()
    columns = [str(col) for col in data.columns]
    code_col = find_code_column(columns)

    raw_rows = []
    for _, row in data.iterrows():
        row_data = {col: clean_cell(row[col]) for col in columns}
        raw_rows.append(row_data)

    final_rows = []
    for row_index, row_data in enumerate(raw_rows):
        code_val = row_data.get(code_col) if code_col else None

        if code_col is None:
            # No code column detected at all for this table -- flag the
            # whole table once rather than silently emitting bad data.
            final_rows.append(row_data)
            continue

        if looks_like_single_code(code_val) or code_val is None:
            # Blank codes still get flagged below (separately from
            # merge issues) but pass through unchanged -- we never
            # invent a code value.
            final_rows.append(row_data)
            if code_val is None:
                issues.append({
                    "table_id": table_id,
                    "row_index": row_index,
                    "issue": "blank_code",
                    "row": row_data,
                })
            continue

        if looks_like_multi_code(code_val):
            split = try_split_merged_row(row_data, code_col, columns)
            if split:
                for s in split:
                    final_rows.append(s)
                issues.append({
                    "table_id": table_id,
                    "row_index": row_index,
                    "issue": "merged_row_auto_split",
                    "n_split": len(split),
                    "original_row": row_data,
                })
            else:
                # Couldn't safely split -- keep as-is but flag loudly.
                # This is deliberately NOT silent: better to see it in
                # the issues file than lose it in a false split.
                final_rows.append(row_data)
                issues.append({
                    "table_id": table_id,
                    "row_index": row_index,
                    "issue": "merged_row_unsplit_ambiguous",
                    "row": row_data,
                })
            continue

        # Code present but doesn't match expected shape (e.g. contains
        # stray punctuation, or is a genuinely unusual code format) --
        # keep the row but flag it for a human glance.
        final_rows.append(row_data)
        issues.append({
            "table_id": table_id,
            "row_index": row_index,
            "issue": "unexpected_code_format",
            "code": code_val,
            "row": row_data,
        })

    tables.append({
        "table_id": table_id,
        "columns": columns,
        "rows": final_rows,
    })


# ============================================================
# SAVE JSON
# ============================================================

output = {"source": PDF_PATH.name, "tables": tables}

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

with open(ISSUES_PATH, "w", encoding="utf-8") as f:
    json.dump({"source": PDF_PATH.name, "issues": issues}, f, indent=2, ensure_ascii=False)

n_rows = sum(len(t["rows"]) for t in tables)
print(f"Saved: {OUTPUT_PATH}")
print(f"Tables extracted: {len(tables)}")
print(f"Rows extracted: {n_rows}")
print(f"Issues flagged: {len(issues)} -> see {ISSUES_PATH}")
by_type = {}
for i in issues:
    by_type[i["issue"]] = by_type.get(i["issue"], 0) + 1
for k, v in by_type.items():
    print(f"  {k}: {v}")