"""
PDF -> hierarchical Markdown + normalized JSON

Outputs:
    1. Hierarchical Markdown
    2. Normalized JSON containing:
        - complete document text
        - blocks
        - headings
        - heading paths
        - document-adaptive section IDs
        - parent headings
        - page numbers
        - bounding boxes
        - table content

The code is document/provider agnostic.

The JSON is intended to be the intermediate representation
for later structure-aware hierarchical chunking.
"""

from pathlib import Path
import json
from collections import Counter

from docling.document_converter import DocumentConverter
from docling_core.types.doc import TextItem, TableItem

from hierarchical.postprocessor import ResultPostprocessor


# ============================================================
# CONFIG
# ============================================================

# Change this for each PDF you want to test.
PDF_PATH = Path("/home/vijaykumar/Desktop/project2/Lab_Management/raw/Cigna_Lab_Management.pdf").resolve()

OUTPUT_DIR = Path("/home/vijaykumar/Desktop/project2/Lab_Management/md")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MD_PATH = OUTPUT_DIR / f"{PDF_PATH.stem}_hierarchical.md"
JSON_PATH = OUTPUT_DIR / f"{PDF_PATH.stem}_hierarchical.json"


# ============================================================
# HELPERS
# ============================================================

def get_provenance(item):
    """
    Extract page number and bounding box from a Docling item.
    """

    prov_list = getattr(item, "prov", None)

    if not prov_list:
        return {
            "page": None,
            "bbox": None
        }

    prov = prov_list[0]

    page = getattr(prov, "page_no", None)

    bbox = getattr(prov, "bbox", None)

    if bbox is not None:
        bbox = [
            bbox.l,
            bbox.t,
            bbox.r,
            bbox.b
        ]

    return {
        "page": page,
        "bbox": bbox
    }


def get_item_type(item):
    """
    Convert Docling item types into a simpler representation.
    """

    if isinstance(item, TableItem):
        return "table"

    if isinstance(item, TextItem):

        label = str(
            getattr(item, "label", "")
        ).lower()

        if "title" in label:
            return "title"

        if "section_header" in label:
            return "heading"

        if "list" in label:
            return "list"

        if "caption" in label:
            return "caption"

        if "formula" in label:
            return "formula"

        return "paragraph"

    return item.__class__.__name__.lower()


def get_item_text(item, document):
    """
    Extract textual content from an item.

    Tables are exported as Markdown so their textual
    representation is retained in the JSON.
    """

    if isinstance(item, TableItem):

        try:
            return item.export_to_markdown(
                doc=document
            )

        except Exception:
            return str(item)

    text = getattr(item, "text", None)

    if text is not None:
        return text

    return ""


# ============================================================
# DOCUMENT-ADAPTIVE SECTION DETECTION
# ============================================================

def detect_section_level(headings):
    """
    Determine which heading level appears to represent
    major sections in THIS document.

    We do not assume:
        #    = main
        ##   = main
        ###  = main

    Instead, we inspect the document's heading structure.

    Strategy:

    1. Collect heading levels.
    2. Prefer the shallowest level that has multiple
       meaningful headings.
    3. If only one heading exists at the shallowest level,
       use the next level if it has multiple siblings.

    This is intentionally conservative.

    Returns:
        section_level
    """

    if not headings:
        return None

    level_counts = Counter(
        h["heading_level"]
        for h in headings
        if h["heading_level"] is not None
    )

    if not level_counts:
        return None

    levels = sorted(level_counts)

    # --------------------------------------------------------
    # Prefer the shallowest level with multiple headings.
    # --------------------------------------------------------

    for level in levels:

        if level_counts[level] >= 2:
            return level

    # --------------------------------------------------------
    # If there is only one heading at every level,
    # use the shallowest level.
    # --------------------------------------------------------

    return levels[0]


def is_section_heading(
    heading_level,
    section_level
):
    """
    Determine whether a heading is a major section.
    """

    if heading_level is None:
        return False

    if section_level is None:
        return False

    return heading_level == section_level


# ============================================================
# 1. CONVERT PDF
# ============================================================

print("=" * 70)
print("DOCUMENT PARSING")
print("=" * 70)

print(f"PDF: {PDF_PATH}")

converter = DocumentConverter()

result = converter.convert(
    str(PDF_PATH)
)


# ============================================================
# 2. RECOVER HEADING HIERARCHY
# ============================================================

print()
print("Recovering heading hierarchy...")

ResultPostprocessor(result).process()

document = result.document


# ============================================================
# 3. EXPORT MARKDOWN
# ============================================================

print()
print("Exporting Markdown...")

# IMPORTANT:
#
# This is the same export that was already producing good
# hierarchical Markdown for you.
#
# We do NOT modify it.

markdown = document.export_to_markdown()

MD_PATH.write_text(
    markdown,
    encoding="utf-8"
)


# ============================================================
# 4. FIRST PASS
#    Collect headings
# ============================================================

print()
print("Analyzing heading structure...")

raw_items = []

reading_order = 0

for item, level in document.iterate_items():

    reading_order += 1

    item_type = get_item_type(item)

    item_text = get_item_text(
        item,
        document
    )

    provenance = get_provenance(item)

    raw_items.append({
        "item": item,
        "reading_order": reading_order,
        "type": item_type,
        "text": item_text,
        "level": level,
        "page": provenance["page"],
        "bbox": provenance["bbox"]
    })


# ============================================================
# 5. COLLECT HEADINGS
# ============================================================

headings = []

for entry in raw_items:

    if entry["type"] not in {
        "heading",
        "title"
    }:
        continue

    headings.append({
        "reading_order": entry["reading_order"],
        "text": entry["text"].strip(),
        "heading_level": entry["level"],
        "page": entry["page"]
    })


# ============================================================
# 6. DETECT MAJOR SECTION LEVEL
# ============================================================

section_level = detect_section_level(
    headings
)

print()
print(f"Detected major section level: {section_level}")

if section_level is None:
    print(
        "WARNING: No reliable heading level detected."
    )


# ============================================================
# 7. BUILD NORMALIZED BLOCKS
# ============================================================

print()
print("Building normalized blocks...")

blocks = []

heading_stack = {}

current_section_id = None
current_section_title = None

section_counter = 0

for entry in raw_items:

    reading_order = entry["reading_order"]

    block_id = f"b{reading_order:05d}"

    item_type = entry["type"]

    item_text = entry["text"]

    level = entry["level"]

    page = entry["page"]

    bbox = entry["bbox"]

    is_heading = (
        item_type in {
            "heading",
            "title"
        }
    )

    # ========================================================
    # HEADING
    # ========================================================

    if is_heading:

        heading_level = level

        # ----------------------------------------------------
        # Is this a MAJOR SECTION?
        # ----------------------------------------------------

        is_main_section = is_section_heading(
            heading_level,
            section_level
        )

        if is_main_section:

            section_counter += 1

            current_section_id = (
                f"s{section_counter:04d}"
            )

            current_section_title = (
                item_text.strip()
            )

        # ----------------------------------------------------
        # Update heading stack
        # ----------------------------------------------------

        for old_level in list(
            heading_stack.keys()
        ):

            if old_level >= heading_level:
                del heading_stack[old_level]

        heading_stack[heading_level] = {
            "block_id": block_id,
            "text": item_text.strip(),
            "level": heading_level
        }

        # ----------------------------------------------------
        # Heading path
        # ----------------------------------------------------

        heading_path = [
            heading_stack[level]["text"]
            for level in sorted(heading_stack)
        ]

        # ----------------------------------------------------
        # Immediate parent
        # ----------------------------------------------------

        parent_heading = None
        parent_heading_id = None

        parent_levels = [
            l
            for l in heading_stack
            if l < heading_level
        ]

        if parent_levels:

            parent_level = max(
                parent_levels
            )

            parent_heading = (
                heading_stack[
                    parent_level
                ]["text"]
            )

            parent_heading_id = (
                heading_stack[
                    parent_level
                ]["block_id"]
            )

    # ========================================================
    # NON-HEADING
    # ========================================================

    else:

        if heading_stack:

            current_heading_level = max(
                heading_stack
            )

            current_heading = (
                heading_stack[
                    current_heading_level
                ]
            )

            parent_heading = (
                current_heading["text"]
            )

            parent_heading_id = (
                current_heading["block_id"]
            )

            heading_path = [
                heading_stack[level]["text"]
                for level in sorted(
                    heading_stack
                )
            ]

        else:

            parent_heading = None
            parent_heading_id = None
            heading_path = []


    # ========================================================
    # CREATE BLOCK
    # ========================================================

    block = {

        "block_id": block_id,

        "reading_order": reading_order,

        "type": item_type,

        "heading_level": (
            level
            if is_heading
            else None
        ),

        "text": item_text,

        "page": page,

        "bbox": bbox,

        # ----------------------------------------------------
        # Document-adaptive section
        # ----------------------------------------------------

        "section_id": current_section_id,

        "section_title": current_section_title,

        # ----------------------------------------------------
        # Detailed hierarchy
        # ----------------------------------------------------

        "parent_heading_id": (
            parent_heading_id
        ),

        "parent_heading": (
            parent_heading
        ),

        "heading_path": heading_path
    }


    # ========================================================
    # TABLE DATA
    # ========================================================

    item = entry["item"]

    if isinstance(item, TableItem):

        try:

            dataframe = item.export_to_dataframe(
                doc=document
            )

            block["table"] = {

                "headers": [
                    str(column)
                    for column in dataframe.columns
                ],

                "rows": [
                    [
                        value
                        for value in row
                    ]
                    for row in dataframe.values.tolist()
                ]
            }

        except Exception as e:

            block["table"] = {
                "error": str(e)
            }


    # ========================================================
    # ADD BLOCK
    # ========================================================

    blocks.append(block)


# ============================================================
# 8. COMPLETE DOCUMENT TEXT
# ============================================================

# IMPORTANT:
#
# Do NOT rebuild this from blocks.
#
# Markdown is the complete textual representation produced
# by the processed Docling document.

complete_text = markdown


# ============================================================
# 9. SECTION SUMMARY
# ============================================================

sections = []

seen_sections = set()

for block in blocks:

    section_id = block["section_id"]

    if section_id is None:
        continue

    if section_id in seen_sections:
        continue

    seen_sections.add(section_id)

    sections.append({
        "section_id": section_id,
        "title": block["section_title"],
        "first_block_id": block["block_id"],
        "first_page": block["page"]
    })


# ============================================================
# 10. FINAL JSON
# ============================================================

structured_document = {

    "document": {

        "source": PDF_PATH.name,

        "source_path": str(PDF_PATH),

        "total_pages": len(
            getattr(document, "pages", {})
        ),

        "section_level": section_level,

        "text": complete_text
    },

    "sections": sections,

    "blocks": blocks
}


# ============================================================
# 11. WRITE JSON
# ============================================================

print()
print("Writing JSON...")

with JSON_PATH.open(
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        structured_document,
        f,
        indent=2,
        ensure_ascii=False,
        default=str
    )


# ============================================================
# 12. SUMMARY
# ============================================================

print()
print("=" * 70)
print("DONE")
print("=" * 70)

print(f"Markdown        : {MD_PATH}")
print(f"JSON            : {JSON_PATH}")
print()
print(f"Document text   : {len(complete_text):,} characters")
print(f"Blocks          : {len(blocks):,}")
print(f"Headings        : {len(headings):,}")
print(f"Sections        : {len(sections):,}")
print(f"Detected level  : {section_level}")
print()
print("Detected sections:")

for section in sections:

    print(
        f"  {section['section_id']} "
        f"→ {section['title']}"
    )

print()
print("JSON contains:")
print("  ✓ Complete document text")
print("  ✓ Reading order")
print("  ✓ Heading hierarchy")
print("  ✓ Heading paths")
print("  ✓ Document-adaptive section IDs")
print("  ✓ Parent heading relationships")
print("  ✓ Page numbers")
print("  ✓ Bounding boxes")
print("  ✓ Tables + structured rows")