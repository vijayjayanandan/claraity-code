"""Tests for PDF and Word document reading in ReadFileTool.

Tests are organized into:
- TestExtractorModule: Direct unit tests for document_extractor.py functions
- TestReadPDF: Integration tests for PDF reading via ReadFileTool (subprocess)
- TestReadDOCX: Integration tests for DOCX reading via ReadFileTool (subprocess)
- TestDocumentSecurity: Security guards (file size, zip bomb, line cap, crash isolation)
- TestDocumentEdgeCases: Edge cases and metadata
"""

import json
import subprocess
import zipfile

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.tools import ReadFileTool
from src.tools.file_operations import FileOperationTool
from src.tools.base import ToolStatus
from src.tools.document_extractor import extract_pdf, extract_docx, check_zip_bomb


@pytest.fixture(autouse=True)
def allow_test_workspace(tmp_path, monkeypatch):
    """Allow file operations in test tmp_path."""
    monkeypatch.setattr(FileOperationTool, "_workspace_root", tmp_path)
    yield
    monkeypatch.setattr(FileOperationTool, "_workspace_root", None)


def _make_subprocess_result(lines, error=None, returncode=0):
    """Create a mock subprocess.CompletedProcess with JSON output."""
    data = {"lines": lines, "error": error}
    result = MagicMock(spec=subprocess.CompletedProcess)
    result.stdout = json.dumps(data)
    result.stderr = ""
    result.returncode = returncode
    return result


# ---------------------------------------------------------------------------
# Extractor module unit tests (no subprocess, direct function calls)
# ---------------------------------------------------------------------------


class TestExtractorModule:
    """Direct tests for document_extractor.py extraction functions."""

    def test_extract_pdf_basic(self, tmp_path):
        """Test PDF extraction produces page headers and text."""
        import fitz

        # Create a real minimal PDF with text
        pdf_path = tmp_path / "test.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Hello PDF World")
        doc.save(str(pdf_path))
        doc.close()

        lines, error = extract_pdf(pdf_path, max_lines=10_000)

        assert error is None
        assert any("--- Page 1 of 1 ---" in line for line in lines)
        assert any("Hello PDF World" in line for line in lines)

    def test_extract_pdf_line_cap(self, tmp_path):
        """Test PDF extraction respects max_lines limit."""
        import fitz

        pdf_path = tmp_path / "big.pdf"
        doc = fitz.open()
        page = doc.new_page()
        # Insert many lines of text
        for i in range(100):
            page.insert_text((72, 72 + i * 8), f"Line {i}")
        doc.save(str(pdf_path))
        doc.close()

        lines, error = extract_pdf(pdf_path, max_lines=10)

        assert error is None
        assert len(lines) == 11  # 10 lines + truncation notice
        assert "extraction stopped" in lines[-1]

    def test_extract_docx_basic(self, tmp_path):
        """Test DOCX extraction produces paragraph text."""
        from docx import Document

        docx_path = tmp_path / "test.docx"
        doc = Document()
        doc.add_paragraph("Hello")
        doc.add_paragraph("World")
        doc.save(str(docx_path))

        lines, error = extract_docx(docx_path, max_lines=10_000,
                                     max_zip_size=200 * 1024 * 1024, max_zip_ratio=100)

        assert error is None
        assert "Hello" in lines
        assert "World" in lines

    def test_extract_docx_with_table(self, tmp_path):
        """Test DOCX extraction includes tables."""
        from docx import Document

        docx_path = tmp_path / "table.docx"
        doc = Document()
        doc.add_paragraph("Before")
        table = doc.add_table(rows=2, cols=2)
        table.rows[0].cells[0].text = "A"
        table.rows[0].cells[1].text = "B"
        table.rows[1].cells[0].text = "C"
        table.rows[1].cells[1].text = "D"
        doc.save(str(docx_path))

        lines, error = extract_docx(docx_path, max_lines=10_000,
                                     max_zip_size=200 * 1024 * 1024, max_zip_ratio=100)

        assert error is None
        assert "Before" in lines
        assert any("[Table 1]" in line for line in lines)
        assert any("| A | B |" in line for line in lines)

    def test_extract_docx_line_cap(self, tmp_path):
        """Test DOCX extraction respects max_lines limit."""
        from docx import Document

        docx_path = tmp_path / "big.docx"
        doc = Document()
        for i in range(50):
            doc.add_paragraph(f"Paragraph {i}")
        doc.save(str(docx_path))

        lines, error = extract_docx(docx_path, max_lines=10,
                                     max_zip_size=200 * 1024 * 1024, max_zip_ratio=100)

        assert error is None
        assert len(lines) == 11  # 10 lines + truncation notice
        assert "extraction stopped" in lines[-1]

    def test_check_zip_bomb_normal_file(self, tmp_path):
        """Test that normal DOCX passes zip bomb check."""
        from docx import Document

        docx_path = tmp_path / "normal.docx"
        doc = Document()
        doc.add_paragraph("Normal content")
        doc.save(str(docx_path))

        result = check_zip_bomb(docx_path)
        assert result is None

    def test_check_zip_bomb_high_ratio(self, tmp_path):
        """Test that suspicious compression ratio is detected."""
        # Create a ZIP with artificially high compression ratio
        zip_path = tmp_path / "bomb.docx"
        with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
            # Write highly compressible data (1MB of zeros)
            zf.writestr("word/document.xml", "\x00" * (1024 * 1024))

        result = check_zip_bomb(zip_path, max_ratio=5)
        assert result is not None
        assert "compression ratio" in result.lower() or "Suspicious" in result


# ---------------------------------------------------------------------------
# PDF integration tests (ReadFileTool -> subprocess)
# ---------------------------------------------------------------------------


class TestReadPDF:
    """Integration tests for PDF reading via ReadFileTool subprocess."""

    def test_pdf_basic_text(self, tmp_path):
        """Test PDF text extraction via subprocess."""
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 dummy")

        mock_result = _make_subprocess_result(
            ["--- Page 1 of 1 ---", "", "Line one", "Line two", "Line three"]
        )

        tool = ReadFileTool()
        with patch("src.tools.file_operations.subprocess.run", return_value=mock_result):
            result = tool.execute(file_path=str(pdf_path))

        assert result.status == ToolStatus.SUCCESS
        assert "Line one" in result.output
        assert "Line two" in result.output
        assert "--- Page 1 of 1 ---" in result.output

    def test_pdf_multi_page(self, tmp_path):
        """Test multi-page PDF output."""
        pdf_path = tmp_path / "multi.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 dummy")

        mock_result = _make_subprocess_result([
            "--- Page 1 of 3 ---", "", "Page one content", "",
            "--- Page 2 of 3 ---", "", "Page two content", "",
            "--- Page 3 of 3 ---", "", "Page three content", "",
        ])

        tool = ReadFileTool()
        with patch("src.tools.file_operations.subprocess.run", return_value=mock_result):
            result = tool.execute(file_path=str(pdf_path))

        assert result.status == ToolStatus.SUCCESS
        assert "--- Page 1 of 3 ---" in result.output
        assert "--- Page 3 of 3 ---" in result.output

    def test_pdf_with_tables(self, tmp_path):
        """Test PDF table extraction output."""
        pdf_path = tmp_path / "tables.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 dummy")

        mock_result = _make_subprocess_result([
            "--- Page 1 of 1 ---", "", "Some text", "",
            "[Table 1]", "| Name | Age |", "| Alice | 30 |",
        ])

        tool = ReadFileTool()
        with patch("src.tools.file_operations.subprocess.run", return_value=mock_result):
            result = tool.execute(file_path=str(pdf_path))

        assert result.status == ToolStatus.SUCCESS
        assert "[Table 1]" in result.output
        assert "| Name | Age |" in result.output
        assert "| Alice | 30 |" in result.output

    def test_pdf_line_range(self, tmp_path):
        """Test line range selection on PDF output."""
        pdf_path = tmp_path / "range.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 dummy")

        mock_result = _make_subprocess_result(
            [f"Line {i}" for i in range(20)]
        )

        tool = ReadFileTool()
        with patch("src.tools.file_operations.subprocess.run", return_value=mock_result):
            result = tool.execute(file_path=str(pdf_path), start_line=3, max_lines=2)

        assert result.status == ToolStatus.SUCCESS
        assert result.metadata["lines_returned"] == 2
        assert result.metadata["start_line"] == 3
        assert result.metadata["has_more"] is True

    def test_pdf_extractor_returns_error(self, tmp_path):
        """Test handling when extractor subprocess reports an error."""
        pdf_path = tmp_path / "bad.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 dummy")

        mock_result = _make_subprocess_result(
            [], error="PyMuPDF is required to read PDF files. Install it: pip install PyMuPDF"
        )

        tool = ReadFileTool()
        with patch("src.tools.file_operations.subprocess.run", return_value=mock_result):
            result = tool.execute(file_path=str(pdf_path))

        assert result.status == ToolStatus.ERROR
        assert "PyMuPDF" in result.error


# ---------------------------------------------------------------------------
# DOCX integration tests (real files through subprocess)
# ---------------------------------------------------------------------------


class TestReadDOCX:
    """Integration tests for Word document reading."""

    def _create_docx_with_text(self, path: Path, paragraphs: list[str]):
        """Create a real .docx file with given paragraphs."""
        from docx import Document

        doc = Document()
        for text in paragraphs:
            doc.add_paragraph(text)
        doc.save(str(path))

    def _create_docx_with_table(self, path: Path, headers: list[str], rows: list[list[str]]):
        """Create a real .docx file with a paragraph and a table."""
        from docx import Document

        doc = Document()
        doc.add_paragraph("Text before table")
        table = doc.add_table(rows=1, cols=len(headers))
        for i, header in enumerate(headers):
            table.rows[0].cells[i].text = header
        for row_data in rows:
            row = table.add_row()
            for i, cell in enumerate(row_data):
                row.cells[i].text = cell
        doc.add_paragraph("Text after table")
        doc.save(str(path))

    def test_docx_basic_text(self, tmp_path):
        """Test extracting paragraphs from a Word document."""
        docx_path = tmp_path / "test.docx"
        self._create_docx_with_text(docx_path, ["Hello", "World", "Test"])

        tool = ReadFileTool()
        result = tool.execute(file_path=str(docx_path))

        assert result.status == ToolStatus.SUCCESS
        assert "Hello" in result.output
        assert "World" in result.output
        assert "Test" in result.output

    def test_docx_with_table(self, tmp_path):
        """Test extracting a table from a Word document."""
        docx_path = tmp_path / "table.docx"
        self._create_docx_with_table(
            docx_path,
            headers=["Name", "Score"],
            rows=[["Alice", "95"], ["Bob", "87"]],
        )

        tool = ReadFileTool()
        result = tool.execute(file_path=str(docx_path))

        assert result.status == ToolStatus.SUCCESS
        assert "[Table 1]" in result.output
        assert "| Name | Score |" in result.output
        assert "Text before table" in result.output

    def test_docx_preserves_order(self, tmp_path):
        """Test that paragraphs and tables appear in document order."""
        from docx import Document

        docx_path = tmp_path / "order.docx"
        doc = Document()
        doc.add_paragraph("First paragraph")
        table = doc.add_table(rows=1, cols=2)
        table.rows[0].cells[0].text = "A"
        table.rows[0].cells[1].text = "B"
        doc.add_paragraph("Second paragraph")
        doc.save(str(docx_path))

        tool = ReadFileTool()
        result = tool.execute(file_path=str(docx_path))

        assert result.status == ToolStatus.SUCCESS
        lines = result.output
        first_pos = lines.find("First paragraph")
        table_pos = lines.find("[Table 1]")
        second_pos = lines.find("Second paragraph")
        assert first_pos < table_pos < second_pos

    def test_docx_empty_document(self, tmp_path):
        """Test reading an empty Word document."""
        from docx import Document

        docx_path = tmp_path / "empty.docx"
        doc = Document()
        doc.save(str(docx_path))

        tool = ReadFileTool()
        result = tool.execute(file_path=str(docx_path))

        assert result.status == ToolStatus.SUCCESS

    def test_docx_line_range(self, tmp_path):
        """Test that start_line/max_lines work on DOCX output."""
        docx_path = tmp_path / "range.docx"
        self._create_docx_with_text(docx_path, [f"Para {i}" for i in range(20)])

        tool = ReadFileTool()
        result = tool.execute(file_path=str(docx_path), start_line=5, max_lines=3)

        assert result.status == ToolStatus.SUCCESS
        assert result.metadata["lines_returned"] == 3
        assert result.metadata["start_line"] == 5
        assert result.metadata["has_more"] is True


# ---------------------------------------------------------------------------
# Security tests
# ---------------------------------------------------------------------------


class TestDocumentSecurity:
    """Security guards: file size, zip bomb, line cap, crash isolation."""

    def test_file_size_limit_rejects_large_pdf(self, tmp_path):
        """Test that PDFs exceeding MAX_DOCUMENT_SIZE_BYTES are rejected."""
        pdf_path = tmp_path / "huge.pdf"
        pdf_path.write_bytes(b"x" * 1000)

        tool = ReadFileTool()
        tool.MAX_DOCUMENT_SIZE_BYTES = 500  # Set low for testing

        result = tool.execute(file_path=str(pdf_path))

        assert result.status == ToolStatus.ERROR
        assert "too large" in result.error

    def test_file_size_limit_rejects_large_docx(self, tmp_path):
        """Test that DOCX exceeding MAX_DOCUMENT_SIZE_BYTES are rejected."""
        docx_path = tmp_path / "huge.docx"
        docx_path.write_bytes(b"x" * 1000)

        tool = ReadFileTool()
        tool.MAX_DOCUMENT_SIZE_BYTES = 500

        result = tool.execute(file_path=str(docx_path))

        assert result.status == ToolStatus.ERROR
        assert "too large" in result.error

    def test_file_size_limit_allows_small_files(self, tmp_path):
        """Test that files under the limit are processed normally."""
        from docx import Document

        docx_path = tmp_path / "small.docx"
        doc = Document()
        doc.add_paragraph("Small file")
        doc.save(str(docx_path))

        tool = ReadFileTool()
        # Default 10MB limit should easily allow this
        result = tool.execute(file_path=str(docx_path))

        assert result.status == ToolStatus.SUCCESS

    def test_zip_bomb_detected(self, tmp_path):
        """Test that DOCX zip bombs are rejected by the extractor."""
        zip_path = tmp_path / "bomb.docx"
        with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
            # Write highly compressible data
            zf.writestr("word/document.xml", "\x00" * (2 * 1024 * 1024))

        # Use the extractor directly to test the zip bomb guard
        lines, error = extract_docx(
            zip_path, max_lines=10_000,
            max_zip_size=200 * 1024 * 1024, max_zip_ratio=5  # Very strict ratio
        )

        assert error is not None
        assert "compression ratio" in error.lower() or "Suspicious" in error

    def test_subprocess_crash_returns_error(self, tmp_path):
        """Test that a subprocess crash (e.g. segfault) returns an error, not a crash."""
        pdf_path = tmp_path / "crash.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 dummy")

        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_result.returncode = -11  # SIGSEGV

        tool = ReadFileTool()
        with patch("src.tools.file_operations.subprocess.run", return_value=mock_result):
            result = tool.execute(file_path=str(pdf_path))

        assert result.status == ToolStatus.ERROR
        assert "corrupt or unsupported" in result.error

    def test_subprocess_timeout_returns_error(self, tmp_path):
        """Test that a subprocess timeout returns an error gracefully."""
        pdf_path = tmp_path / "slow.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 dummy")

        tool = ReadFileTool()
        with patch(
            "src.tools.file_operations.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="test", timeout=30),
        ):
            result = tool.execute(file_path=str(pdf_path))

        assert result.status == ToolStatus.ERROR
        assert "timed out" in result.error

    def test_subprocess_bad_json_returns_error(self, tmp_path):
        """Test that garbled subprocess output returns an error."""
        pdf_path = tmp_path / "garbled.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 dummy")

        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.stdout = "NOT JSON {{{{"
        mock_result.stderr = ""
        mock_result.returncode = 0

        tool = ReadFileTool()
        with patch("src.tools.file_operations.subprocess.run", return_value=mock_result):
            result = tool.execute(file_path=str(pdf_path))

        assert result.status == ToolStatus.ERROR

    def test_error_message_sanitized(self, tmp_path):
        """Test that internal error details are not leaked to the LLM."""
        pdf_path = tmp_path / "err.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 dummy")

        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_result.returncode = 1  # Non-zero = crash

        tool = ReadFileTool()
        with patch("src.tools.file_operations.subprocess.run", return_value=mock_result):
            result = tool.execute(file_path=str(pdf_path))

        assert result.status == ToolStatus.ERROR
        # Should show generic message, not internal paths or tracebacks
        assert "corrupt or unsupported" in result.error

    def test_corrupt_pdf_via_subprocess(self, tmp_path):
        """Test that a truly corrupt PDF file is handled gracefully end-to-end."""
        pdf_path = tmp_path / "corrupt.pdf"
        pdf_path.write_bytes(b"this is not a pdf at all")

        # Let it run the real subprocess - the extractor should catch the error
        tool = ReadFileTool()
        result = tool.execute(file_path=str(pdf_path))

        assert result.status == ToolStatus.ERROR

    def test_corrupt_docx_via_subprocess(self, tmp_path):
        """Test that a truly corrupt DOCX file is handled gracefully end-to-end."""
        docx_path = tmp_path / "corrupt.docx"
        docx_path.write_bytes(b"this is not a docx at all")

        tool = ReadFileTool()
        result = tool.execute(file_path=str(docx_path))

        assert result.status == ToolStatus.ERROR


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestDocumentEdgeCases:
    """Edge cases shared across document formats."""

    def test_unknown_binary_format_not_intercepted(self, tmp_path):
        """Test that non-PDF/DOCX binary files are NOT routed to extractors."""
        bin_path = tmp_path / "data.bin"
        bin_path.write_bytes(b"\x00\x01\x02\x03")

        tool = ReadFileTool()
        result = tool.execute(file_path=str(bin_path))

        assert result.status == ToolStatus.SUCCESS

    def test_pdf_extension_case_insensitive(self, tmp_path):
        """Test that .PDF (uppercase) is still routed to the extractor."""
        pdf_path = tmp_path / "test.PDF"
        pdf_path.write_bytes(b"%PDF-1.4 dummy")

        mock_result = _make_subprocess_result(
            ["--- Page 1 of 1 ---", "", "Upper case extension"]
        )

        tool = ReadFileTool()
        with patch("src.tools.file_operations.subprocess.run", return_value=mock_result):
            result = tool.execute(file_path=str(pdf_path))

        assert result.status == ToolStatus.SUCCESS
        assert "Upper case extension" in result.output

    def test_metadata_structure(self, tmp_path):
        """Test that metadata from document reads matches plain text read structure."""
        from docx import Document

        docx_path = tmp_path / "meta.docx"
        doc = Document()
        doc.add_paragraph("Test line")
        doc.save(str(docx_path))

        tool = ReadFileTool()
        result = tool.execute(file_path=str(docx_path))

        assert result.metadata is not None
        required_keys = {"file_path", "total_lines", "lines_returned", "start_line", "end_line", "has_more"}
        assert required_keys.issubset(set(result.metadata.keys()))

    def test_text_file_unaffected(self, tmp_path):
        """Test that plain text files still use the streaming path, not subprocess."""
        txt_path = tmp_path / "plain.txt"
        txt_path.write_text("line 1\nline 2\nline 3\n")

        tool = ReadFileTool()
        result = tool.execute(file_path=str(txt_path))

        assert result.status == ToolStatus.SUCCESS
        assert "line 1" in result.output
        assert result.metadata["total_lines"] == 3
