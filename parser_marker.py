from pathlib import Path

from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered


# ============================================================
# Configuration
# ============================================================

INPUT_DIR = Path(
    "/home/vijaykumar/Downloads/prior auth/project/data/raw"
)

OUTPUT_DIR = Path(
    "/home/vijaykumar/Downloads/prior auth/project/data/markdown_marker"
)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)



converter = PdfConverter(
    artifact_dict=create_model_dict(),
)



pdf_files = list(INPUT_DIR.glob("*.pdf"))

print(f"Found {len(pdf_files)} PDF files")

for pdf_path in pdf_files:

    print(f"\nProcessing: {pdf_path.name}")

    try:
        # Convert PDF
        rendered = converter(str(pdf_path))

        # Extract markdown
        markdown_text, _, images = text_from_rendered(rendered)

        # Output filename
        output_file = OUTPUT_DIR / f"{pdf_path.stem}.md"

        # Save Markdown
        output_file.write_text(
            markdown_text,
            encoding="utf-8"
        )

        print(f"Saved: {output_file}")

    except Exception as e:
        print(f"ERROR processing {pdf_path.name}")
        print(e)


print("\nConversion complete.")