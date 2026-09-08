from docling.document_converter import DocumentConverter
from collections import Counter

converter = DocumentConverter()
result = converter.convert("/home/vijaykumar/Desktop/project/extra_pdfs/Table.pdf")
doc = result.document

# See what docling actually detected, label by label
labels = Counter(item.label for item, _ in doc.iterate_items())
print("Label counts:", labels)

# Dump first 40 items raw so we can see what's really in there
for i, (item, depth) in enumerate(doc.iterate_items()):
    if i > 40:
        break
    text_preview = getattr(item, "text", "")[:80]
    print(f'{i:3} depth={depth} label={item.label} :: {text_preview!r}')