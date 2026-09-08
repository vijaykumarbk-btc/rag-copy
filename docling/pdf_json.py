import json
from pathlib import Path

from docling.document_converter import DocumentConverter


# ============================================================
# CONFIG
# ============================================================

PDF_PATH = Path("data/raw/Cigna_ACDF.pdf")
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

JSON_PATH = OUTPUT_DIR / f"{PDF_PATH.stem}.json"
MD_PATH = OUTPUT_DIR / f"{PDF_PATH.stem}.md"


# ============================================================
# CONVERT PDF
# ============================================================

converter = DocumentConverter()

result = converter.convert(PDF_PATH)

doc = result.document


# ============================================================
# 1. SAVE NATIVE DOCLING JSON
# ============================================================

with JSON_PATH.open("w", encoding="utf-8") as f:
    json.dump(
        doc.export_to_dict(),
        f,
        ensure_ascii=False,
        indent=2,
    )


# ============================================================
# 2. SAVE MARKDOWN
# ============================================================

markdown = doc.export_to_markdown()

MD_PATH.write_text(
    markdown,
    encoding="utf-8",
)


print("Conversion complete.")
print(f"JSON: {JSON_PATH}")
print(f"Markdown: {MD_PATH}")