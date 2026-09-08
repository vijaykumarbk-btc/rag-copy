
import argparse
import glob
import os
import re
import sys
from collections import defaultdict

import pymupdf  # PyMuPDF (import name "fitz" also works)


DIGIT_RUN = re.compile(r"\d+")


def normalize_text(text: str) -> str:
    """Collapse whitespace and blank out digit runs so that things like
    page numbers ("Page 5 of 34") still count as the *same* repeating
    string across pages."""
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    text = DIGIT_RUN.sub("#", text)
    return text


def is_horizontal(line_dir) -> bool:
    """line_dir is a (dx, dy) unit vector for the text line's writing
    direction. Horizontal text has dy ~= 0."""
    return abs(line_dir[1]) < 0.1


def collect_spans(doc):
    """Returns list-of-pages, each a list of span dicts:
    {text, bbox, rotated}"""
    pages_spans = []
    for page in doc:
        spans = []
        d = page.get_text("dict")
        for block in d["blocks"]:
            if block["type"] != 0:  # skip images
                continue
            for line in block["lines"]:
                horiz = is_horizontal(line["dir"])
                for span in line["spans"]:
                    txt = span["text"]
                    if not txt.strip():
                        continue
                    spans.append(
                        {
                            "text": txt,
                            "norm": normalize_text(txt),
                            "bbox": span["bbox"],
                            "rotated": not horiz,
                        }
                    )
        pages_spans.append(spans)
    return pages_spans


def find_boilerplate(pages_spans, page_rect, min_repeat_fraction, min_repeat_pages,
                      grid=8):
    """Group spans by (rounded position, normalized text). A group that
    shows up on enough distinct pages is boilerplate. Returns a set of
    group keys considered boilerplate, plus per-page span membership."""
    n_pages = len(pages_spans)
    groups = defaultdict(set)  # key -> set(page indices)
    key_of_span = {}  # (page_idx, span_id) -> key

    for pidx, spans in enumerate(pages_spans):
        for sidx, s in enumerate(spans):
            x0, y0, x1, y1 = s["bbox"]
            gx = round(x0 / grid) * grid
            gy = round(y0 / grid) * grid
            key = (s["norm"], gx, gy, s["rotated"])
            groups[key].add(pidx)
            key_of_span[(pidx, sidx)] = key

    threshold = max(min_repeat_pages, int(round(min_repeat_fraction * n_pages)))
    # Rotated (watermark) text needs a lower bar: it repeats by nature,
    # but there are usually fewer distinct rotated strings to average over.
    rotated_threshold = min(threshold, max(2, int(round(0.15 * n_pages))))

    boilerplate_keys = set()
    for key, page_set in groups.items():
        _, _, _, rotated = key
        needed = rotated_threshold if rotated else threshold
        if len(page_set) >= needed:
            boilerplate_keys.add(key)

    return boilerplate_keys, key_of_span


def build_redactions(pages_spans, page_rect, boilerplate_keys, key_of_span, pad=2.0):
    """For each page, compute the redaction rectangles:
    - header band / footer band (full page width) from horizontal boilerplate
    - individual padded boxes for rotated (watermark) boilerplate
    Returns list-of-pages of pymupdf.Rect."""
    page_h = page_rect.height
    page_w = page_rect.width
    mid_y = page_h / 2

    per_page_rects = []
    for pidx, spans in enumerate(pages_spans):
        header_y0, header_y1 = None, None
        footer_y0, footer_y1 = None, None
        rotated_rects = []

        for sidx, s in enumerate(spans):
            key = key_of_span[(pidx, sidx)]
            if key not in boilerplate_keys:
                continue
            x0, y0, x1, y1 = s["bbox"]

            if s["rotated"]:
                rotated_rects.append(
                    pymupdf.Rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad)
                )
                continue

            center = (y0 + y1) / 2
            if center < mid_y:  # header candidate
                header_y0 = y0 if header_y0 is None else min(header_y0, y0)
                header_y1 = y1 if header_y1 is None else max(header_y1, y1)
            else:  # footer candidate
                footer_y0 = y0 if footer_y0 is None else min(footer_y0, y0)
                footer_y1 = y1 if footer_y1 is None else max(footer_y1, y1)

        rects = list(rotated_rects)
        if header_y0 is not None:
            rects.append(pymupdf.Rect(0, max(0, header_y0 - pad), page_w, header_y1 + pad))
        if footer_y0 is not None:
            rects.append(
                pymupdf.Rect(0, footer_y0 - pad, page_w, min(page_h, footer_y1 + pad))
            )
        per_page_rects.append(rects)

    return per_page_rects


def clean_pdf(in_path, out_path, min_repeat_fraction=0.5, min_repeat_pages=3,
              dry_run=False, verbose=False):
    doc = pymupdf.open(in_path)
    if len(doc) == 0:
        print(f"  [skip] {in_path}: no pages")
        return

    pages_spans = collect_spans(doc)
    page_rect = doc[0].rect

    boilerplate_keys, key_of_span = find_boilerplate(
        pages_spans, page_rect, min_repeat_fraction, min_repeat_pages
    )

    if verbose:
        print(f"  Detected {len(boilerplate_keys)} boilerplate text group(s):")
        seen = set()
        for pidx, spans in enumerate(pages_spans):
            for sidx, s in enumerate(spans):
                key = key_of_span[(pidx, sidx)]
                if key in boilerplate_keys and key not in seen:
                    seen.add(key)
                    kind = "watermark(rotated)" if key[3] else "header/footer"
                    print(f"    [{kind}] {s['text'][:60]!r}")

    per_page_rects = build_redactions(
        pages_spans, page_rect, boilerplate_keys, key_of_span
    )

    if dry_run:
        total = sum(len(r) for r in per_page_rects)
        print(f"  [dry-run] would remove {total} region(s) across {len(doc)} page(s)")
        doc.close()
        return

    for page, rects in zip(doc, per_page_rects):
        for r in rects:
            page.add_redact_annot(r, fill=(1, 1, 1))
        if rects:
            page.apply_redactions()

    doc.save(out_path, garbage=4, deflate=True)
    doc.close()
    print(f"  -> {out_path}")


def main():
    ap = argparse.ArgumentParser(
        description="Strip repeating headers/footers/watermarks from PDFs (generic, no hardcoding)."
    )
    ap.add_argument("inputs", nargs="+", help="PDF file(s) or glob pattern(s)")
    ap.add_argument("-o", "--output", help="Output path (only valid for a single input file)")
    ap.add_argument("--outdir", help="Directory to write cleaned PDFs into (for multiple files)")
    ap.add_argument("--suffix", default=".cleaned", help="Suffix for output filenames (default: .cleaned)")
    ap.add_argument(
        "--min-repeat-fraction",
        type=float,
        default=0.5,
        help="Fraction of pages a text block must repeat on (at the same spot) to count as "
        "header/footer boilerplate (default 0.5)",
    )
    ap.add_argument(
        "--min-repeat-pages",
        type=int,
        default=3,
        help="Minimum absolute number of pages a text block must repeat on (default 3)",
    )
    ap.add_argument("--dry-run", action="store_true", help="Report what would be removed, don't write output")
    ap.add_argument("-v", "--verbose", action="store_true", help="Print detected boilerplate text")
    args = ap.parse_args()

    files = []
    for pattern in args.inputs:
        matches = glob.glob(pattern)
        files.extend(matches if matches else [pattern])
    files = sorted(set(files))

    if not files:
        print("No input files found.")
        sys.exit(1)

    if args.output and len(files) > 1:
        print("--output can only be used with a single input file; use --outdir for multiple.")
        sys.exit(1)

    for f in files:
        if not os.path.isfile(f):
            print(f"  [skip] {f}: not found")
            continue

        if args.output:
            out_path = args.output
        else:
            base, ext = os.path.splitext(f)
            out_name = f"{base}{args.suffix}{ext}"
            if args.outdir:
                os.makedirs(args.outdir, exist_ok=True)
                out_path = os.path.join(args.outdir, os.path.basename(out_name))
            else:
                out_path = out_name

        print(f"Processing {f} ...")
        clean_pdf(
            f,
            out_path,
            min_repeat_fraction=args.min_repeat_fraction,
            min_repeat_pages=args.min_repeat_pages,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )


if __name__ == "__main__":
    main()