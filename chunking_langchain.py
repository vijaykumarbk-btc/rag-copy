from langchain_text_splitters import MarkdownHeaderTextSplitter
from pathlib import Path

import numpy as np

document = Path("/home/vijaykumar/Downloads/prior auth/project/data/chunks/Cigna_ACDF_chunks.json")
output = Path("/home/vijaykumar/Downloads/prior auth/project/data/embeddings/Cigna_Langchain.npy")

text = document.read_text(encoding="utf-8")
headers_to_spliton = [("#","Header 1")]

markdown_splitter = MarkdownHeaderTextSplitter(headers_to_spliton,strip_headers=False)

chunks = markdown_splitter.split_text(text)
print(chunks[:5])

np.save(output, np.array(chunks, dtype=object))