"""Structural and cross-record validation for OCR metadata v1."""

from functools import lru_cache
from pathlib import Path
import math

from jsonschema import Draft202012Validator, validators

from .io import ensure_json_value, read_json, relative_path


SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas"
SCHEMA_NAMES = frozenset({
    "page_metadata", "line_metadata", "recognized_line", "metadata_bundle",
})


class MetadataValidationError(ValueError):
    """Contract violation with the relevant record location or identity."""


def _is_number(checker, value):
    if type(value) is int:
        return True
    return type(value) is float and math.isfinite(value)


STRICT_TYPES = Draft202012Validator.TYPE_CHECKER.redefine(
    "integer", lambda checker, value: type(value) is int,
).redefine("number", _is_number)
StrictValidator = validators.extend(Draft202012Validator, type_checker=STRICT_TYPES)


@lru_cache(maxsize=4)
def _validator(name):
    if name not in SCHEMA_NAMES:
        raise MetadataValidationError(f"Unsupported schema: {name}")
    entry = read_json(SCHEMA_ROOT / f"{name}.schema.json")
    definitions = read_json(SCHEMA_ROOT / "definitions.schema.json")["$defs"]
    prefix = "definitions.schema.json#/$defs/"
    reference = entry["$ref"]
    if not reference.startswith(prefix):
        raise MetadataValidationError("Schema references must use local definitions")
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": definitions,
        "$ref": "#/$defs/" + reference.removeprefix(prefix),
    }
    Draft202012Validator.check_schema(schema)
    return StrictValidator(schema)


def validate_structure(name, value):
    """Validate a record or wrapper without checking cross-record relationships."""
    try:
        ensure_json_value(value)
    except ValueError as error:
        raise MetadataValidationError(str(error)) from error
    error = next(_validator(name).iter_errors(value), None)
    if error is not None:
        path = ".".join(map(str, error.absolute_path)) or "root"
        raise MetadataValidationError(f"{name}.{path}: {error.message}")


def line_key(record):
    return tuple(record[field] for field in ("exam_id", "page_id", "line_id"))


def line_ref(record):
    return {field: record[field] for field in ("exam_id", "page_id", "line_id")}


def _check_path(value, location):
    try:
        relative_path(value)
    except ValueError as error:
        raise MetadataValidationError(f"{location}: {error}") from error


def _check_transform(page, location):
    matrix = page["original_to_processed"]
    if matrix[2] != [0, 0, 1]:
        raise MetadataValidationError(f"{location}: the last affine row must be [0, 0, 1]")
    a, b, _ = matrix[0]
    c, d, _ = matrix[1]
    try:
        determinant = a * d - b * c
        usable = determinant != 0 and math.isfinite(determinant)
    except OverflowError:
        usable = False
    if not usable:
        raise MetadataValidationError(f"{location}: matrix is singular or exceeds the numeric range")


def _require_error_issue(record, location):
    if not any(issue["severity"] == "error" for issue in record["issues"]):
        raise MetadataValidationError(f"{location}: error status requires an issue with severity=error")


def validate_bundle(value):
    """Validate an entire run without reading images or modifying the input."""
    validate_structure("metadata_bundle", value)
    page_map, page_indexes = {}, []
    for index, page in enumerate(value["pages"]):
        location = f"pages[{index}] ({page['page_id']})"
        if page["exam_id"] != value["exam_id"] or page["page_id"] in page_map:
            raise MetadataValidationError(f"{location}: mismatched exam_id or duplicate page_id")
        page_map[page["page_id"]] = page
        page_indexes.append(page["page_index"])
        for field in ("original_image_path", "processed_image_path"):
            _check_path(page[field], f"{location}.{field}")
        _check_transform(page, location)
        if page["status"] in ("failed", "review_required"):
            _require_error_issue(page, location)
    if sorted(page_indexes) != list(range(1, len(page_indexes) + 1)):
        raise MetadataValidationError("pages.page_index: values must be unique and contiguous from 1")

    keys, crop_paths, detection_keys = set(), set(), set()
    orders = {page_id: [] for page_id in page_map}
    for index, line in enumerate(value["lines"]):
        location = f"lines[{index}] ({line['page_id']}/{line['line_id']})"
        if line["exam_id"] != value["exam_id"] or line["page_id"] not in page_map:
            raise MetadataValidationError(f"{location}: mismatched exam_id or unknown page")
        key = line_key(line)
        if key in keys:
            raise MetadataValidationError(f"{location}: duplicate line key {key}")
        keys.add(key)
        _check_path(line["image_path"], f"{location}.image_path")
        if line["image_path"] in crop_paths:
            raise MetadataValidationError(f"{location}: duplicate crop path")
        crop_paths.add(line["image_path"])
        if "source_detection_id" in line:
            detection_key = (line["page_id"], line["source_detection_id"])
            if detection_key in detection_keys:
                raise MetadataValidationError(f"{location}: duplicate source_detection_id within the page")
            detection_keys.add(detection_key)
        page = page_map[line["page_id"]]
        x0, y0, x1, y1 = line["bbox"]
        size = page["processed_size"]
        if not (0 <= x0 < x1 <= size["width"] and 0 <= y0 < y1 <= size["height"]):
            raise MetadataValidationError(f"{location}.bbox: empty or outside processed_size")
        orders[line["page_id"]].append(line["reading_order"])
        if value["stage"] == "ocr":
            if line["status"] == "ok" and not line["text"].strip():
                raise MetadataValidationError(f"{location}: ok requires nonblank text")
            if line["status"] == "empty_prediction" and line["text"] != "":
                raise MetadataValidationError(f"{location}: empty_prediction requires text=''")
            if line["status"] in ("empty_prediction", "failed"):
                _require_error_issue(line, location)

    for page_id, page_orders in orders.items():
        if sorted(page_orders) != list(range(1, len(page_orders) + 1)):
            raise MetadataValidationError(f"page {page_id}: reading_order must be contiguous from 1")
        status = page_map[page_id]["status"]
        if status == "blank" and page_orders:
            raise MetadataValidationError(f"page {page_id}: blank pages cannot contain lines")
        if status == "ok" and not page_orders:
            raise MetadataValidationError(f"page {page_id}: ok requires at least one line")

    for collection in ("pages", "lines"):
        for index, record in enumerate(value[collection]):
            for issue_index, issue in enumerate(record.get("issues", [])):
                refs = [line_key(ref) for ref in issue["refs"]]
                if len(set(refs)) != len(refs) or any(ref not in keys for ref in refs):
                    raise MetadataValidationError(
                        f"{collection}[{index}].issues[{issue_index}].refs: duplicate or unresolved references"
                    )
