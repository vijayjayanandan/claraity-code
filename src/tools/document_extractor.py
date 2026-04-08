"""
Subprocess-safe document text extractor.

This module is designed to run as a child process via `python -m src.tools.document_extractor`.
It extracts text from PDF and DOCX files and writes JSON to stdout.

Running in a subprocess isolates the main agent from C-level crashes in
PyMuPDF's MuPDF library. If the parser segfaults, only this child process
dies -- the agent receives a non-zero exit code and reports an error.

Usage:
    python -m src.tools.document_extractor <file_path> [--format pdf|docx]
        [--max-lines 10000] [--max-zip-size 209715200] [--max-zip-ratio 100]

Output (stdout): JSON object with keys:
    - "lines": list of extracted text lines (no line numbers)
    - "error": error string if extraction failed, null otherwise
"""

import argparse
import json
import sys
import zipfile
from pathlib import Path


def check_zip_bomb(
    path: Path,
    max_decompressed: int = 200 * 1024 * 1024,
    max_ratio: int = 100,
) -> str | None:
    """Check DOCX ZIP for decompression bomb. Returns error string or None."""
    try:
        with zipfile.ZipFile(str(path), "r") as zf:
            total = sum(info.file_size for info in zf.infolist())
            compressed = path.stat().st_size

            if total > max_decompressed:
                return (
                    f"DOCX decompressed size too large: {total:,} bytes "
                    f"(limit: {max_decompressed:,})"
                )
            if compressed > 0 and (total / compressed) > max_ratio:
                return (
                    f"Suspicious compression ratio: {total / compressed:.0f}:1 "
                    f"(limit: {max_ratio}:1)"
                )
    except zipfile.BadZipFile:
        pass  # Let the document library handle it
    return None


def extract_pdf(path: Path, max_lines: int) -> tuple[list[str], str | None]:
    """Extract text and tables from a PDF file."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return [], "PyMuPDF is required to read PDF files. Install it: pip install PyMuPDF"

    lines: list[str] = []
    try:
        doc = fitz.open(str(path))
    except Exception as e:
        return [], f"Failed to open PDF: {e}"

    try:
        for page_num in range(len(doc)):
            page = doc[page_num]

            lines.append(f"--- Page {page_num + 1} of {len(doc)} ---")
            lines.append("")

            text = page.get_text()
            if text.strip():
                for line in text.splitlines():
                    lines.append(line)
                    if len(lines) >= max_lines:
                        lines.append(
                            f"[... extraction stopped: exceeded {max_lines:,} lines.]"
                        )
                        return lines, None

            if hasattr(page, "find_tables"):
                tables = page.find_tables()
                for table_idx, table in enumerate(tables):
                    data = table.extract()
                    if data:
                        lines.append("")
                        lines.append(f"[Table {table_idx + 1}]")
                        for row in data:
                            cells = [str(c) if c is not None else "" for c in row]
                            lines.append("| " + " | ".join(cells) + " |")
                            if len(lines) >= max_lines:
                                lines.append(
                                    f"[... extraction stopped: exceeded {max_lines:,} lines.]"
                                )
                                return lines, None

            lines.append("")
    except Exception as e:
        return [], f"Failed to extract PDF text: {e}"
    finally:
        doc.close()

    return lines, None


def extract_docx(
    path: Path,
    max_lines: int,
    max_zip_size: int,
    max_zip_ratio: int,
) -> tuple[list[str], str | None]:
    """Extract text and tables from a DOCX file."""
    # Zip bomb guard
    bomb_error = check_zip_bomb(path, max_zip_size, max_zip_ratio)
    if bomb_error:
        return [], bomb_error

    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError:
        return [], "python-docx is required to read Word files. Install it: pip install python-docx"

    try:
        doc = Document(str(path))
    except Exception as e:
        return [], f"Failed to open DOCX: {e}"

    lines: list[str] = []
    table_idx = 0

    para_map: dict[int, Paragraph] = {id(p._element): p for p in doc.paragraphs}
    table_map: dict[int, Table] = {id(t._element): t for t in doc.tables}

    for element in doc.element.body:
        elem_id = id(element)

        if elem_id in para_map:
            lines.append(para_map[elem_id].text)
            if len(lines) >= max_lines:
                lines.append(
                    f"[... extraction stopped: exceeded {max_lines:,} lines.]"
                )
                return lines, None

        elif elem_id in table_map:
            table_idx += 1
            table = table_map[elem_id]
            lines.append("")
            lines.append(f"[Table {table_idx}]")
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                lines.append("| " + " | ".join(cells) + " |")
                if len(lines) >= max_lines:
                    lines.append(
                        f"[... extraction stopped: exceeded {max_lines:,} lines.]"
                    )
                    return lines, None
            lines.append("")

    return lines, None


def main() -> None:
    import os

    parser = argparse.ArgumentParser(description="Extract text from PDF/DOCX files")
    parser.add_argument("file_path", help="Path to the document")
    parser.add_argument("--format", choices=["pdf", "docx"], help="Document format (auto-detected from extension if omitted)")
    parser.add_argument("--max-lines", type=int, default=10_000, help="Max lines to extract")
    parser.add_argument("--max-zip-size", type=int, default=200 * 1024 * 1024, help="Max DOCX decompressed size")
    parser.add_argument("--max-zip-ratio", type=int, default=100, help="Max DOCX compression ratio")
    args = parser.parse_args()

    # Suppress library messages (e.g. PyMuPDF's "Consider using pymupdf_layout")
    # that print to stdout and pollute the JSON output.
    real_stdout = sys.stdout
    devnull_out = open(os.devnull, "w")
    devnull_err = open(os.devnull, "w")
    sys.stdout = devnull_out
    sys.stderr = devnull_err

    path = Path(args.file_path)
    if not path.is_file():
        output = {"lines": [], "error": f"File not found: {args.file_path}"}
        sys.stdout = real_stdout
        json.dump(output, real_stdout)
        return

    fmt = args.format or path.suffix.lower().lstrip(".")

    if fmt == "pdf":
        lines, error = extract_pdf(path, args.max_lines)
    elif fmt == "docx":
        lines, error = extract_docx(path, args.max_lines, args.max_zip_size, args.max_zip_ratio)
    else:
        lines, error = [], f"Unsupported format: {fmt}"

    # Restore stdout and clean up
    sys.stdout = real_stdout
    devnull_out.close()
    devnull_err.close()
    output = {"lines": lines, "error": error}
    json.dump(output, real_stdout)


if __name__ == "__main__":
    main()
