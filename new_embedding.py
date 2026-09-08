from openai import OpenAI
from dotenv import load_dotenv

import os
import json
import re


# ============================================================
# Configuration
# ============================================================

load_dotenv()

EMBEDDING_MODEL_URL = os.getenv("EMBEDDING_MODEL_URL")

MODEL = "hf.co/unsloth/embeddinggemma-300m-GGUF:Q8_0"

INPUT_FILE = (
    "/home/vijaykumar/Downloads/prior auth/project/"
    "data/chunks/Cigna_ACDF_chunks.json"
)

OUTPUT_FILE = (
    "/home/vijaykumar/Downloads/prior auth/project/"
    "data/embeddings/Cigna_ACDF_embeddings.json"
)


# ============================================================
# Validate environment
# ============================================================

if not EMBEDDING_MODEL_URL:
    raise ValueError(
        "EMBEDDING_MODEL_URL is not set in .env"
    )


# ============================================================
# Create OpenAI client
# Connected to your Ollama embedding server
# ============================================================

client = OpenAI(
    base_url=EMBEDDING_MODEL_URL,
    api_key="ollama"
)


# ============================================================
# Load chunks
# ============================================================

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

print(f"Loaded {len(data)} chunks")


# ============================================================
# Get entire document text
# Used to extract document-level metadata
# ============================================================

full_document_text = "\n".join(
    chunk.get("text", "")
    for chunk in data
)


# ============================================================
# Extract VERSION
#
# Example:
# Comprehensive Musculoskeletal Management Guidelines V1.0.2026
# ============================================================

version_match = re.search(
    r"\bV\d+\.\d+\.\d{4}\b",
    full_document_text
)

if version_match:
    version = version_match.group(0)
else:
    version = ""


# ============================================================
# Extract EFFECTIVE DATE
#
# Example:
# Effective Date: August 04, 2026
# ============================================================

effective_date_match = re.search(
    r"Effective Date:\s*"
    r"([A-Za-z]+\s+\d{1,2},\s+\d{4})",
    full_document_text,
    re.IGNORECASE
)

if effective_date_match:
    effective_date = effective_date_match.group(1)
else:
    effective_date = ""


print(f"Version: {version}")
print(f"Effective Date: {effective_date}")


# ============================================================
# Generate embeddings
# ============================================================

data_to_save = {}


for i, current in enumerate(data):

    # --------------------------------------------------------
    # Original chunk fields
    # --------------------------------------------------------

    chunk_id = current["chunk_id"]

    text = current.get("text", "")

    parent_section = current.get(
        "parent_section",
        ""
    )

    subsection = current.get(
        "subsection",
        ""
    )

    section = current.get(
        "section",
        ""
    )

    section_type = current.get(
        "section_type",
        ""
    )

    source = current.get(
        "source",
        ""
    )


    # ========================================================
    # Header 1
    # ========================================================

    header_1 = parent_section


    # ========================================================
    # Header 2
    # ========================================================

    header_2 = subsection


    # ========================================================
    # Guideline path
    #
    # Your chunk already contains this:
    #
    # General Guidelines >
    # Urgent/Emergent Indications/Conditions
    #
    # Therefore, don't reconstruct it unnecessarily.
    # ========================================================

    guideline_path = section


    # ========================================================
    # Generate embedding
    #
    # IMPORTANT:
    # Embed the actual chunk text.
    # ========================================================

    response = client.embeddings.create(
        model=MODEL,
        input=text
    )

    embedding = response.data[0].embedding


    # ========================================================
    # Create final output structure
    # ========================================================

    data_to_save[str(chunk_id)] = {

        "metadata": {

            "Header_1": header_1,

            "Header_2": header_2,

            "guideline_path": guideline_path,

            "section_type": section_type,

            "source": source,

            "version": version,

            "effective_date": effective_date
        },

        "content": text,

        "embedding": embedding
    }


    print(
        f"Completed chunk "
        f"{i + 1}/{len(data)} "
        f"(chunk_id={chunk_id})"
    )


# ============================================================
# Create output directory
# ============================================================

os.makedirs(
    os.path.dirname(OUTPUT_FILE),
    exist_ok=True
)


# ============================================================
# Save embeddings JSON
# ============================================================

with open(
    OUTPUT_FILE,
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        data_to_save,
        f,
        indent=2,
        ensure_ascii=False
    )


# ============================================================
# Print results
# ============================================================

print()
print("============================================")
print("Embedding generation completed")
print("============================================")

print(
    f"Total chunks embedded: "
    f"{len(data_to_save)}"
)

if data_to_save:

    first_chunk = next(
        iter(data_to_save.values())
    )

    print(
        f"Embedding dimension: "
        f"{len(first_chunk['embedding'])}"
    )

print()
print("Output:")
print(OUTPUT_FILE)