"""
Parse PDF with Docling and recover proper heading hierarchy
using docling-hierarchical-pdf.

Outputs:
    1. Hierarchical Markdown
    2. Structured Docling JSON

The Markdown structure remains unchanged from the existing pipeline.
"""

from pathlib import Path
import json

from docling.document_converter import DocumentConverter
from hierarchical.postprocessor import ResultPostprocessor


# ============================================================
# CONFIG
# ============================================================

PDF_PATH = Path("data/raw/Cigna_ACDF.pdf")

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MD_PATH = OUTPUT_DIR / f"{PDF_PATH.stem}_hierarchical.md"
JSON_PATH = OUTPUT_DIR / f"{PDF_PATH.stem}_hierarchical.json"


# ============================================================
# 1. Convert PDF with Docling
# ============================================================

print(f"Converting: {PDF_PATH}")

converter = DocumentConverter()

result = converter.convert(str(PDF_PATH))


# ============================================================
# 2. Recover heading hierarchy
# ============================================================

print("Recovering heading hierarchy...")

# This modifies result.document in-place.
ResultPostprocessor(result).process()


# ============================================================
# 3. Export hierarchical Markdown
# ============================================================

print("Exporting Markdown...")

markdown = result.document.export_to_markdown()

MD_PATH.write_text(
    markdown,
    encoding="utf-8"
)


# ============================================================
# 4. Export structured JSON
# ============================================================

print("Exporting structured JSON...")

# Docling's document object can be serialized directly.
# This preserves the underlying document structure rather
# than trying to reconstruct JSON from Markdown.

doc_dict = result.document.model_dump(
    mode="json",
    exclude_none=True
)

with JSON_PATH.open("w", encoding="utf-8") as f:
    json.dump(
        doc_dict,
        f,
        indent=2,
        ensure_ascii=False
    )


# ============================================================
# 5. Summary
# ============================================================

print()
print("=" * 60)
print("DONE")
print("=" * 60)

print(f"Markdown : {MD_PATH}")
print(f"JSON     : {JSON_PATH}")
print(f"MD size  : {len(markdown):,} characters")