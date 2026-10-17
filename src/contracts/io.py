"""Strict UTF-8 JSON reading and artifact path resolution."""

import json
import math
from pathlib import Path, PurePosixPath


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_constant(value):
    raise ValueError(f"Non-finite JSON number: {value}")


def ensure_json_value(value, location="root"):
    """Reject non-JSON Python types, non-finite numbers, and invalid Unicode."""
    if value is None or type(value) in (bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{location}: non-finite number")
        return
    if isinstance(value, str):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeError as error:
            raise ValueError(f"{location}: invalid Unicode") from error
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            ensure_json_value(item, f"{location}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{location}: JSON object keys must be strings")
            ensure_json_value(key, location)
            ensure_json_value(item, f"{location}.{key}")
        return
    raise ValueError(f"{location}: unsupported JSON value type")


def loads_json(text):
    value = json.loads(
        text, object_pairs_hook=_unique_object, parse_constant=_reject_constant,
    )
    ensure_json_value(value)
    return value


def read_json(path):
    return loads_json(Path(path).read_text(encoding="utf-8", errors="strict"))


def write_json(path, value):
    ensure_json_value(value)
    content = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    Path(path).write_text(content, encoding="utf-8")


def relative_path(value):
    if not isinstance(value, str) or not value.strip() or "\\" in value or ":" in value:
        raise ValueError("Expected a nonempty relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path == PurePosixPath("."):
        raise ValueError(f"Unsafe relative path: {value!r}")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("Path contains control characters")
    # Require canonical paths so different strings cannot identify the same crop.
    if path.as_posix() != value:
        raise ValueError(f"Path is not normalized: {value!r}")
    return path


def resolve_path(root, value):
    """Prevent paths and symlinks from escaping the caller-provided root."""
    base = Path(root).resolve()
    path = (base / relative_path(value)).resolve()
    if not path.is_relative_to(base):
        raise ValueError(f"Path escapes artifact root: {value!r}")
    return path
