"""Strict structured-output validation shared by LLM adapters."""

from __future__ import annotations

import json

from pydantic import BaseModel, ValidationError

from app.ports.errors import PermanentPortError

__all__ = ["parse_structured", "repair_instruction"]


def parse_structured(text: str, schema: type[BaseModel]) -> BaseModel:
    """Parse and validate one JSON document without accepting markdown wrappers."""
    try:
        return schema.model_validate_json(text)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise PermanentPortError(
            "provider output did not satisfy the requested response schema",
            port="llm_provider",
            cause=exc,
        ) from exc


def repair_instruction(schema: type[BaseModel]) -> str:
    """Return a deterministic repair instruction containing the authoritative schema."""
    rendered = json.dumps(schema.model_json_schema(), sort_keys=True, separators=(",", ":"))
    return (
        "Return only one JSON document that validates against this JSON Schema. "
        f"Do not use markdown fences or commentary: {rendered}"
    )
