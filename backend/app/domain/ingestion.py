"""Typed deterministic Phase 5 ingestion values and structure-aware chunking."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "CHUNKER_VERSION",
    "ChunkLocator",
    "DocumentBlock",
    "DocumentChunk",
    "DocumentFormat",
    "ParsedDocument",
    "StructureKind",
    "chunk_document",
]

CHUNKER_VERSION: Final[Literal["agora-whitespace-v1"]] = "agora-whitespace-v1"
_TOKEN = re.compile(r"\S+")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class DocumentFormat(StrEnum):
    PDF = "PDF"
    DOCX = "DOCX"
    TXT = "TXT"
    MARKDOWN = "MARKDOWN"
    CSV = "CSV"
    XLSX = "XLSX"
    JSON = "JSON"
    HTML = "HTML"


class StructureKind(StrEnum):
    HEADING = "HEADING"
    PARAGRAPH = "PARAGRAPH"
    TABLE_ROW = "TABLE_ROW"
    DATA = "DATA"


class ChunkLocator(_FrozenModel):
    page: int | None = Field(default=None, ge=1)
    section: str | None = None
    paragraph: int | None = Field(default=None, ge=1)
    table: int | None = Field(default=None, ge=1)
    row: int | None = Field(default=None, ge=1)
    sheet: str | None = None
    json_path: str | None = None
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)

    @field_validator("section", "sheet", "json_path")
    @classmethod
    def _optional_non_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def _ordered_span(self) -> ChunkLocator:
        if self.char_end <= self.char_start:
            raise ValueError("char_end must be greater than char_start")
        return self


class DocumentBlock(_FrozenModel):
    kind: StructureKind
    text: str = Field(min_length=1)
    locator: ChunkLocator
    repeat_prefix: str | None = None

    @field_validator("text", "repeat_prefix")
    @classmethod
    def _non_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value


class ParsedDocument(_FrozenModel):
    format: DocumentFormat
    parser: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    blocks: tuple[DocumentBlock, ...]
    warnings: tuple[str, ...] = ()

    @field_validator("parser", "parser_version")
    @classmethod
    def _non_blank_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("warnings")
    @classmethod
    def _non_blank_warnings(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not warning.strip() for warning in value):
            raise ValueError("warnings must not be blank")
        return value


class DocumentChunk(_FrozenModel):
    ordinal: int = Field(ge=0)
    text: str = Field(min_length=1)
    token_count: int = Field(gt=0)
    locator: ChunkLocator
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    chunker_version: Literal["agora-whitespace-v1"]


def _digest(text: str, locator: ChunkLocator) -> str:
    preimage = {
        "chunker_version": CHUNKER_VERSION,
        "locator": locator.model_dump(mode="json"),
        "text": text,
    }
    encoded = json.dumps(
        preimage, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def chunk_document(
    document: ParsedDocument, *, target_tokens: int = 800, overlap_tokens: int = 150
) -> tuple[DocumentChunk, ...]:
    """Split blocks deterministically without crossing structural boundaries."""
    if target_tokens <= 0:
        raise ValueError("target_tokens must be positive")
    if overlap_tokens < 0 or overlap_tokens >= target_tokens:
        raise ValueError("overlap_tokens must be non-negative and smaller than target_tokens")

    chunks: list[DocumentChunk] = []
    for block in document.blocks:
        matches = tuple(_TOKEN.finditer(block.text))
        if not matches:
            continue
        prefix = block.repeat_prefix
        prefix_count = len(_TOKEN.findall(prefix or ""))
        capacity = max(1, target_tokens - prefix_count)
        preserve_whole_block = block.kind in {StructureKind.HEADING, StructureKind.TABLE_ROW}
        start = 0
        while start < len(matches):
            end = len(matches) if preserve_whole_block else min(start + capacity, len(matches))
            body_start = matches[start].start()
            body_end = matches[end - 1].end()
            body = block.text[body_start:body_end]
            text = f"{prefix}\n{body}" if prefix else body
            locator = block.locator.model_copy(
                update={
                    "char_start": block.locator.char_start + body_start,
                    "char_end": block.locator.char_start + body_end,
                }
            )
            chunks.append(
                DocumentChunk(
                    ordinal=len(chunks),
                    text=text,
                    token_count=len(_TOKEN.findall(text)),
                    locator=locator,
                    content_hash=_digest(text, locator),
                    chunker_version=CHUNKER_VERSION,
                )
            )
            if end == len(matches):
                break
            retained = min(overlap_tokens, capacity - 1)
            start = end - retained
    return tuple(chunks)
