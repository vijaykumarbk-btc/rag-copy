import os
import re
import json



INPUT_DIR = "/home/vijaykumar/Desktop/project2/hierarchical-processing/md/"
OUTPUT_DIR = "/home/vijaykumar/Desktop/project2/hierarchical-processing/md/chunks/"

MAX_CHARS = 6000

os.makedirs(OUTPUT_DIR, exist_ok=True)



HEADING_PATTERN = re.compile(
    r"^(#{1,6})\s+(.+?)\s*$"
)

FENCE_PATTERN = re.compile(
    r"^\s*(```|~~~)"
)



def get_heading(line):

    match = HEADING_PATTERN.match(line.strip())

    if not match:
        return None

    return {
        "level": len(match.group(1)),
        "title": match.group(2).strip()
    }



def is_table_separator(line):

    stripped = line.strip()

    if "|" not in stripped:
        return False

    cells = stripped.strip("|").split("|")

    if not cells:
        return False

    return all(
        re.match(
            r"^\s*:?-{3,}:?\s*$",
            cell
        )
        for cell in cells
    )


def looks_like_table_row(line):


    stripped = line.strip()

    return (
        "|" in stripped
        and len(stripped) > 1
    )


def is_table_start(lines, index):


    if index + 1 >= len(lines):
        return False

    return (
        looks_like_table_row(lines[index])
        and is_table_separator(lines[index + 1])
    )


# ============================================================
# Parse Markdown into logical blocks
# ============================================================

def parse_markdown_blocks(markdown):

    lines = markdown.splitlines()

    blocks = []

    current_text = []

    def flush_text():
        nonlocal current_text

        if current_text:
            text = "\n".join(current_text).strip()

            if text:
                blocks.append({
                    "type": "text",
                    "text": text
                })

            current_text = []

    i = 0

    while i < len(lines):

        line = lines[i]


        if FENCE_PATTERN.match(line):

            flush_text()

            code_lines = [line]

            fence = line.strip()[:3]

            i += 1

            while i < len(lines):

                code_lines.append(lines[i])

                if lines[i].strip().startswith(fence):
                    i += 1
                    break

                i += 1

            blocks.append({
                "type": "code",
                "text": "\n".join(code_lines).strip()
            })

            continue


        heading = get_heading(line)

        if heading:

            flush_text()

            blocks.append({
                "type": "heading",
                "level": heading["level"],
                "title": heading["title"],
                "text": line.strip()
            })

            i += 1
            continue


        if is_table_start(lines, i):

            flush_text()

            table_lines = []

            while i < len(lines):

                current_line = lines[i]

                if (
                    looks_like_table_row(current_line)
                    or is_table_separator(current_line)
                ):
                    table_lines.append(current_line)
                    i += 1
                else:
                    break

            blocks.append({
                "type": "table",
                "text": "\n".join(table_lines).strip()
            })

            continue

        if not line.strip():

            flush_text()

            i += 1
            continue


        current_text.append(line)

        i += 1

    flush_text()

    return blocks



def update_heading_stack(
    heading_stack,
    level,
    title
):

    while (
        heading_stack
        and heading_stack[-1]["level"] >= level
    ):
        heading_stack.pop()

    heading_stack.append({
        "level": level,
        "title": title
    })

    return heading_stack


def classify_heading(title):

    title_lower = title.lower()


    if (
        "code" in title_lower
        or "cpt" in title_lower
        or "procedure code" in title_lower
    ):
        return "codes"

    if (
        "evidence" in title_lower
        or "rationale" in title_lower
    ):
        return "evidence"

    if (
        "reference" in title_lower
        or "bibliography" in title_lower
    ):
        return "references"

    criteria_terms = [
        "criteria",
        "indication",
        "medical necessity",
        "contraindication",
        "non-indication"
    ]

    if any(
        term in title_lower
        for term in criteria_terms
    ):
        return "criteria"

    return "other"


def build_sections(blocks):

    sections = []

    heading_stack = []

    current_blocks = []

    current_heading = None
    current_type = "other"

    def flush_section():

        nonlocal current_blocks

        if not current_blocks:
            return

        sections.append({
            "heading": current_heading.copy()
            if current_heading
            else [],

            "type": current_type,

            "blocks": current_blocks.copy()
        })

        current_blocks = []

    for block in blocks:

        if block["type"] == "heading":

            flush_section()

            level = block["level"]

            heading_stack = update_heading_stack(
                heading_stack,
                level,
                block["title"]
            )

            current_heading = heading_stack.copy()

            current_type = classify_heading(
                block["title"]
            )

            current_blocks.append(block)

        else:


            if current_heading is None:

                current_heading = []

                current_type = "other"

            current_blocks.append(block)

    flush_section()

    return sections



def format_heading_context(headings):

    if not headings:
        return ""

    return " > ".join(
        heading["title"]
        for heading in headings
    )


def get_parent_section(headings):

    if not headings:
        return ""

    return headings[0]["title"]


def get_subsection(headings):

    if len(headings) < 2:
        return ""

    return headings[-1]["title"]



def split_table_block(
    table_text,
    max_chars=MAX_CHARS
):

    lines = table_text.splitlines()

    if len(lines) <= 2:
        return [table_text]

    header = lines[0]
    separator = lines[1]

    rows = lines[2:]

    table_chunks = []

    current_rows = []
    current_length = (
        len(header)
        + len(separator)
    )

    for row in rows:

        row_length = len(row) + 1

        if (
            current_rows
            and current_length + row_length > max_chars
        ):

            table_chunks.append(
                "\n".join(
                    [
                        header,
                        separator,
                        *current_rows
                    ]
                )
            )

            current_rows = []
            current_length = (
                len(header)
                + len(separator)
            )

        current_rows.append(row)
        current_length += row_length

    if current_rows:

        table_chunks.append(
            "\n".join(
                [
                    header,
                    separator,
                    *current_rows
                ]
            )
        )

    return table_chunks



def split_text_blocks(
    blocks,
    max_chars=MAX_CHARS
):

    chunks = []

    current = []
    current_length = 0

    for block in blocks:

        block_text = block["text"]
        block_length = len(block_text)


        if (
            current
            and current_length + block_length > max_chars
        ):

            chunks.append(
                current.copy()
            )

            current = []
            current_length = 0

        current.append(block)
        current_length += block_length

    if current:

        chunks.append(current)

    return chunks

def create_chunks(
    markdown,
    source_file
):

    blocks = parse_markdown_blocks(markdown)

    sections = build_sections(blocks)

    final_chunks = []

    chunk_id = 0

    for section in sections:

        section_heading = section["heading"]

        section_type = section["type"]

        blocks = section["blocks"]

        has_table = any(
            block["type"] == "table"
            for block in blocks
        )

        if has_table:

            current_text_blocks = []

            for block in blocks:


                if block["type"] == "table":

                    # Flush preceding normal text
                    if current_text_blocks:

                        text_chunks = split_text_blocks(
                            current_text_blocks
                        )

                        for text_chunk in text_chunks:

                            text = "\n\n".join(
                                b["text"]
                                for b in text_chunk
                            )

                            final_chunks.append(
                                build_chunk(
                                    chunk_id,
                                    source_file,
                                    section_heading,
                                    section_type,
                                    "text",
                                    text
                                )
                            )

                            chunk_id += 1

                        current_text_blocks = []


                    table_chunks = split_table_block(
                        block["text"]
                    )

                    for table in table_chunks:

                        final_chunks.append(
                            build_chunk(
                                chunk_id,
                                source_file,
                                section_heading,
                                section_type,
                                "table",
                                table
                            )
                        )

                        chunk_id += 1

                else:

                    current_text_blocks.append(block)


            if current_text_blocks:

                text_chunks = split_text_blocks(
                    current_text_blocks
                )

                for text_chunk in text_chunks:

                    text = "\n\n".join(
                        b["text"]
                        for b in text_chunk
                    )

                    final_chunks.append(
                        build_chunk(
                            chunk_id,
                            source_file,
                            section_heading,
                            section_type,
                            "text",
                            text
                        )
                    )

                    chunk_id += 1

            continue


        section_text = "\n\n".join(
            block["text"]
            for block in blocks
        ).strip()


        if len(section_text) <= MAX_CHARS:

            final_chunks.append(
                build_chunk(
                    chunk_id,
                    source_file,
                    section_heading,
                    section_type,
                    (
                        "criteria"
                        if section_type == "criteria"
                        else "text"
                    ),
                    section_text
                )
            )

            chunk_id += 1

            continue

        smaller_chunks = split_text_blocks(
            blocks
        )

        for smaller_chunk in smaller_chunks:

            text = "\n\n".join(
                block["text"]
                for block in smaller_chunk
            ).strip()

            if not text:
                continue

            final_chunks.append(
                build_chunk(
                    chunk_id,
                    source_file,
                    section_heading,
                    section_type,
                    (
                        "criteria"
                        if section_type == "criteria"
                        else "text"
                    ),
                    text
                )
            )

            chunk_id += 1

    return final_chunks


def build_chunk(
    chunk_id,
    source_file,
    headings,
    section_type,
    chunk_type,
    text
):

    heading_context = format_heading_context(
        headings
    )

    return {
        "chunk_id": chunk_id,

        "source": source_file,

        "section": heading_context,

        "parent_section": get_parent_section(
            headings
        ),

        "subsection": get_subsection(
            headings
        ),

        "section_type": section_type,

        "chunk_type": chunk_type,

        "text": text
    }



def process_files():

    for filename in os.listdir(INPUT_DIR):

        if not filename.lower().endswith(".md"):
            continue

        input_path = os.path.join(
            INPUT_DIR,
            filename
        )

        print(
            f"\nProcessing: {filename}"
        )

        with open(
            input_path,
            "r",
            encoding="utf-8"
        ) as f:

            markdown = f.read()


        chunks = create_chunks(
            markdown,
            filename
        )


        output_filename = (
            os.path.splitext(filename)[0]
            + "_chunks.json"
        )

        output_path = os.path.join(
            OUTPUT_DIR,
            output_filename
        )


        with open(
            output_path,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                chunks,
                f,
                indent=2,
                ensure_ascii=False
            )

        criteria_count = sum(
            1
            for c in chunks
            if c["chunk_type"] == "criteria"
        )

        table_count = sum(
            1
            for c in chunks
            if c["chunk_type"] == "table"
        )

        text_count = sum(
            1
            for c in chunks
            if c["chunk_type"] == "text"
        )

        print(
            f"Created {len(chunks)} chunks"
        )

        print(
            f"  Criteria : {criteria_count}"
        )

        print(
            f"  Tables   : {table_count}"
        )

        print(
            f"  Text     : {text_count}"
        )

        print(
            f"Saved → {output_path}"
        )



if __name__ == "__main__":

    process_files()

    print("\nChunking complete.")