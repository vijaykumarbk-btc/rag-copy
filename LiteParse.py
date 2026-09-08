from liteparse import LiteParse
import os

# Input and output folders
INPUT_DIR = "/home/vijaykumar/Downloads/prior auth/project/data/raw"
OUTPUT_DIR = "/home/vijaykumar/Downloads/prior auth/project/data/markdown"

# Create output folder if it doesn't exist
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Initialize LiteParse
parser = LiteParse(
    ocr_enabled=False,
    output_format="markdown",
    image_mode="placeholder",
    extract_links=True,
)

# Process every PDF in the input folder
for item in os.listdir(INPUT_DIR):

    # Skip non-PDF files
    if not item.lower().endswith(".pdf"):
        continue

    input_path = os.path.join(INPUT_DIR, item)

    print(f"Processing: {input_path}")

    try:
        # Parse PDF
        result = parser.parse(input_path)

        # Get Markdown output
        markdown_result = result.text

        # Create output filename
        base_name = os.path.splitext(item)[0]
        output_path = os.path.join(
            OUTPUT_DIR,
            f"{base_name}.md"
        )

        # Save Markdown
        with open(output_path, "w", encoding="utf-8") as file:
            file.write(markdown_result)

        print(f"Markdown saved successfully: {output_path}")

    except Exception as e:
        print(f"Error processing {item}: {e}")

print("\nAll PDFs processed.")