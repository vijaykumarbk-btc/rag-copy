from pathlib import Path
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.base_models import InputFormat
from hierarchical.postprocessor import ResultPostprocessor


def convert_pdf_to_md(pdf_path: str, output_path: str = None):
    pdf_path = Path(pdf_path)
    output_path = Path(output_path) if output_path else pdf_path.with_suffix(".md")

    # Enable table structure extraction
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_table_structure = True
    pipeline_options.table_structure_options.do_cell_matching = True
    pipeline_options.do_ocr = False  # not needed for text-based PDFs

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )

    result = converter.convert(str(pdf_path))
    # ---- DIAGNOSTIC: dump raw text order/position before any fixes ----
    for item in result.document.texts:
        if item.prov:
            p = item.prov[0]
            print(f"page={p.page_no} top={p.bbox.t:.1f} bottom={p.bbox.b:.1f} "
                f"bold={item.formatting.bold if item.formatting else None} "
                f"text={item.text[:60]!r}")
    # Fix heading hierarchy (uses PDF bookmarks/TOC if present,
    # else numbering + font-style inference)
    ResultPostprocessor(result, source=str(pdf_path)).process()

    md_text = result.document.export_to_markdown(image_placeholder="")
    output_path.write_text(md_text, encoding="utf-8")
    print(f"Markdown written to: {output_path}")

    return result.document, md_text


if __name__ == "__main__":
    doc, md_text = convert_pdf_to_md("/home/vijaykumar/Desktop/project/extra_pdfs/Cigna_Radiation_Oncology.cleaned.pdf", "/home/vijaykumar/Desktop/project/extra_pdfs/output.md")