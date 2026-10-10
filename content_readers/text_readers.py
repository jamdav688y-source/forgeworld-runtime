"""Plain text, Markdown, JSON, YAML, CSV, and source-code readers.

Each is a thin, honest wrapper around a standard-library (or, for YAML,
PyYAML's safe_load) parser -- no duplicate parsing logic is written
where json/csv/yaml already provide a safe one. Every reader treats its
input strictly as data: never exec'd, never eval'd, never imported.
"""
from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from content_readers import interface  # noqa: E402

try:
    import yaml  # PyYAML, already present in this environment
    _YAML_AVAILABLE = True
except ImportError:  # pragma: no cover -- exercised only where PyYAML is absent
    yaml = None
    _YAML_AVAILABLE = False


def _decode(data: bytes):
    """Returns (text, error). Never raises -- a decode failure is an
    honest MALFORMED result, not an exception."""
    try:
        return data.decode("utf-8", errors="strict"), None
    except UnicodeDecodeError as exc:
        return None, f"content is not valid UTF-8 text: {exc}"


def _bounded(text: str, max_chars: int):
    if len(text) > max_chars:
        return text[:max_chars], True
    return text, False


class PlainTextReader:
    reader_id = "plain_text_reader"
    reader_version = "1.0.0"

    def read(self, request: interface.ContentReadRequest) -> interface.ContentReadResult:
        text, decode_error = _decode(request.data)
        if text is None:
            return self._malformed(request, decode_error)
        bounded, truncated = _bounded(text, request.limits.max_output_chars)
        return interface.ContentReadResult(
            artifact_id=request.artifact_id, reader_id=self.reader_id, reader_version=self.reader_version,
            content_type="text/plain", status=interface.READ_OK,
            structured_content=None, text_content=bounded,
            metadata={"char_count": len(text), "line_count": text.count("\n") + (1 if text else 0)},
            provenance_reference=request.artifact_id, warnings=(), errors=(),
            truncated=truncated,
            truncation_detail=(f"text_content bounded to max_output_chars={request.limits.max_output_chars}" if truncated else None),
            source_sha256=request.source_sha256,
        )

    def _malformed(self, request, detail):
        return interface.ContentReadResult(
            artifact_id=request.artifact_id, reader_id=self.reader_id, reader_version=self.reader_version,
            content_type="text/plain", status=interface.READ_MALFORMED,
            structured_content=None, text_content=None, metadata={},
            provenance_reference=request.artifact_id, warnings=(), errors=(detail,),
            truncated=False, source_sha256=request.source_sha256,
        )


class MarkdownReader:
    reader_id = "markdown_reader"
    reader_version = "1.0.0"

    def read(self, request: interface.ContentReadRequest) -> interface.ContentReadResult:
        text, decode_error = _decode(request.data)
        if text is None:
            return _text_malformed(self, request, decode_error, "text/markdown")
        bounded, truncated = _bounded(text, request.limits.max_output_chars)
        heading_count = sum(1 for line in text.splitlines() if line.lstrip().startswith("#"))
        warnings = ()
        if not _YAML_AVAILABLE:
            pass  # markdown itself needs no YAML; frontmatter parsing is out of scope for this microphase
        return interface.ContentReadResult(
            artifact_id=request.artifact_id, reader_id=self.reader_id, reader_version=self.reader_version,
            content_type="text/markdown", status=interface.READ_OK,
            structured_content=None, text_content=bounded,
            metadata={
                "char_count": len(text), "heading_count": heading_count,
                "note": "structural heading count only; no markdown AST/rendering library available in this environment",
            },
            provenance_reference=request.artifact_id, warnings=warnings, errors=(),
            truncated=truncated,
            truncation_detail=(f"text_content bounded to max_output_chars={request.limits.max_output_chars}" if truncated else None),
            source_sha256=request.source_sha256,
        )


class SourceCodeReader:
    reader_id = "source_code_reader"
    reader_version = "1.0.0"

    _LANGUAGE_HINTS = {
        ".py": "python", ".js": "javascript", ".ts": "typescript", ".go": "go", ".rs": "rust",
        ".java": "java", ".c": "c", ".cpp": "cpp", ".h": "c-header", ".rb": "ruby", ".sh": "shell",
        ".php": "php",
    }

    def read(self, request: interface.ContentReadRequest) -> interface.ContentReadResult:
        text, decode_error = _decode(request.data)
        if text is None:
            return _text_malformed(self, request, decode_error, "text/x-source-code")
        bounded, truncated = _bounded(text, request.limits.max_output_chars)
        suffix = Path(request.filename).suffix.lower() if request.filename else ""
        return interface.ContentReadResult(
            artifact_id=request.artifact_id, reader_id=self.reader_id, reader_version=self.reader_version,
            content_type="text/x-source-code", status=interface.READ_OK,
            structured_content=None, text_content=bounded,
            metadata={
                "char_count": len(text), "line_count": text.count("\n") + (1 if text else 0),
                "language_hint": self._LANGUAGE_HINTS.get(suffix, "unknown"),
                "note": "treated strictly as data; never imported, executed, or AST-parsed",
            },
            provenance_reference=request.artifact_id, warnings=(), errors=(),
            truncated=truncated,
            truncation_detail=(f"text_content bounded to max_output_chars={request.limits.max_output_chars}" if truncated else None),
            source_sha256=request.source_sha256,
        )


class JSONReader:
    reader_id = "json_reader"
    reader_version = "1.0.0"

    def read(self, request: interface.ContentReadRequest) -> interface.ContentReadResult:
        if len(request.data) > request.limits.max_json_yaml_bytes:
            return self._failed(
                request,
                f"input size {len(request.data)} bytes exceeds max_json_yaml_bytes limit "
                f"{request.limits.max_json_yaml_bytes}; parsing not attempted",
                truncated=True,
            )
        text, decode_error = _decode(request.data)
        if text is None:
            return self._malformed(request, decode_error)
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            return self._malformed(
                request,
                f"content routed to the JSON reader (declared/detected as JSON-shaped) but does not "
                f"parse as valid JSON: {exc}",
            )
        return interface.ContentReadResult(
            artifact_id=request.artifact_id, reader_id=self.reader_id, reader_version=self.reader_version,
            content_type="application/json", status=interface.READ_OK,
            structured_content=value, text_content=None,
            metadata={"top_level_type": type(value).__name__, "key_count": (len(value) if isinstance(value, dict) else None)},
            provenance_reference=request.artifact_id, warnings=(), errors=(),
            truncated=False, source_sha256=request.source_sha256,
        )

    def _malformed(self, request, detail):
        return interface.ContentReadResult(
            artifact_id=request.artifact_id, reader_id=self.reader_id, reader_version=self.reader_version,
            content_type="application/json", status=interface.READ_MALFORMED,
            structured_content=None, text_content=None, metadata={},
            provenance_reference=request.artifact_id, warnings=(), errors=(detail,),
            truncated=False, source_sha256=request.source_sha256,
        )

    def _failed(self, request, detail, truncated=False):
        return interface.ContentReadResult(
            artifact_id=request.artifact_id, reader_id=self.reader_id, reader_version=self.reader_version,
            content_type="application/json", status=interface.READ_FAILED,
            structured_content=None, text_content=None, metadata={},
            provenance_reference=request.artifact_id, warnings=(), errors=(detail,),
            truncated=truncated, truncation_detail=(detail if truncated else None),
            source_sha256=request.source_sha256,
        )


class YAMLReader:
    reader_id = "yaml_reader"
    reader_version = "1.0.0"

    def read(self, request: interface.ContentReadRequest) -> interface.ContentReadResult:
        if not _YAML_AVAILABLE:
            return interface.ContentReadResult(
                artifact_id=request.artifact_id, reader_id=self.reader_id, reader_version=self.reader_version,
                content_type="application/yaml", status=interface.READ_UNSUPPORTED,
                structured_content=None, text_content=None, metadata={},
                provenance_reference=request.artifact_id, warnings=(),
                errors=("PyYAML is not installed in this environment; nothing was installed to close this gap",),
                truncated=False, source_sha256=request.source_sha256,
            )
        if len(request.data) > request.limits.max_json_yaml_bytes:
            return interface.ContentReadResult(
                artifact_id=request.artifact_id, reader_id=self.reader_id, reader_version=self.reader_version,
                content_type="application/yaml", status=interface.READ_FAILED,
                structured_content=None, text_content=None, metadata={},
                provenance_reference=request.artifact_id, warnings=(),
                errors=(f"input exceeds max_json_yaml_bytes limit {request.limits.max_json_yaml_bytes}; parsing not attempted",),
                truncated=True,
                truncation_detail=f"input exceeds max_json_yaml_bytes limit {request.limits.max_json_yaml_bytes}",
                source_sha256=request.source_sha256,
            )
        text, decode_error = _decode(request.data)
        if text is None:
            return _text_malformed(self, request, decode_error, "application/yaml")
        try:
            # safe_load ONLY -- never yaml.load()/UnsafeLoader: this reader
            # must never construct arbitrary Python objects from input.
            value = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            return interface.ContentReadResult(
                artifact_id=request.artifact_id, reader_id=self.reader_id, reader_version=self.reader_version,
                content_type="application/yaml", status=interface.READ_MALFORMED,
                structured_content=None, text_content=None, metadata={},
                provenance_reference=request.artifact_id, warnings=(),
                errors=(f"content does not parse as valid YAML: {exc}",),
                truncated=False, source_sha256=request.source_sha256,
            )
        return interface.ContentReadResult(
            artifact_id=request.artifact_id, reader_id=self.reader_id, reader_version=self.reader_version,
            content_type="application/yaml", status=interface.READ_OK,
            structured_content=value, text_content=None,
            metadata={"top_level_type": type(value).__name__, "parser": "yaml.safe_load"},
            provenance_reference=request.artifact_id, warnings=(), errors=(),
            truncated=False, source_sha256=request.source_sha256,
        )


class CSVReader:
    reader_id = "csv_reader"
    reader_version = "1.0.0"

    def read(self, request: interface.ContentReadRequest) -> interface.ContentReadResult:
        text, decode_error = _decode(request.data)
        if text is None:
            return _text_malformed(self, request, decode_error, "text/csv")
        try:
            reader = csv.reader(io.StringIO(text))
            rows = []
            truncated = False
            for i, row in enumerate(reader):
                if i >= request.limits.max_csv_rows:
                    truncated = True
                    break
                rows.append(row)
        except csv.Error as exc:
            return interface.ContentReadResult(
                artifact_id=request.artifact_id, reader_id=self.reader_id, reader_version=self.reader_version,
                content_type="text/csv", status=interface.READ_MALFORMED,
                structured_content=None, text_content=None, metadata={},
                provenance_reference=request.artifact_id, warnings=(), errors=(f"content does not parse as CSV: {exc}",),
                truncated=False, source_sha256=request.source_sha256,
            )
        return interface.ContentReadResult(
            artifact_id=request.artifact_id, reader_id=self.reader_id, reader_version=self.reader_version,
            content_type="text/csv", status=interface.READ_OK,
            structured_content=rows, text_content=None,
            metadata={"row_count": len(rows), "column_count_first_row": (len(rows[0]) if rows else 0)},
            provenance_reference=request.artifact_id, warnings=(), errors=(),
            truncated=truncated,
            truncation_detail=(f"rows bounded to max_csv_rows={request.limits.max_csv_rows}" if truncated else None),
            source_sha256=request.source_sha256,
        )


def _text_malformed(reader, request, detail, content_type):
    return interface.ContentReadResult(
        artifact_id=request.artifact_id, reader_id=reader.reader_id, reader_version=reader.reader_version,
        content_type=content_type, status=interface.READ_MALFORMED,
        structured_content=None, text_content=None, metadata={},
        provenance_reference=request.artifact_id, warnings=(), errors=(detail,),
        truncated=False, source_sha256=request.source_sha256,
    )


interface.register_reader("text/plain", PlainTextReader())
interface.register_reader("text/markdown", MarkdownReader())
interface.register_reader("text/x-source-code", SourceCodeReader())
interface.register_reader("application/json", JSONReader())
interface.register_reader("application/yaml", YAMLReader())
interface.register_reader("text/csv", CSVReader())
