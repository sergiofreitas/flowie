"""JSON Schema helpers for Codex structured output."""

from __future__ import annotations

import json
from typing import Any


def prepare_output_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Shape Pydantic JSON Schema for Codex/OpenAI structured output.

    Codex passes the schema to OpenAI response formatting, which rejects object
    schemas unless they explicitly forbid undeclared keys.
    """
    prepared = json.loads(json.dumps(schema))
    _forbid_extra_object_keys(prepared)
    return prepared


def _forbid_extra_object_keys(value: Any) -> None:
    if isinstance(value, dict):
        if value.get("type") == "object" or "properties" in value:
            value.setdefault("additionalProperties", False)
        for child in value.values():
            _forbid_extra_object_keys(child)
    elif isinstance(value, list):
        for child in value:
            _forbid_extra_object_keys(child)
