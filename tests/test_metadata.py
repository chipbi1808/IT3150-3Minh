"""Realistic scenarios at the metadata producer and consumer boundary."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from src.contracts.io import loads_json, read_json, resolve_path, write_json
from src.contracts.validators import (
    MetadataValidationError, line_key, line_ref, validate_bundle, validate_structure,
)


ROOT = Path(__file__).resolve().parents[1]


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.segmented = read_json(ROOT / "examples/segmented_pages.json")
        self.recognized = read_json(ROOT / "examples/recognized_lines.json")

    def assert_invalid(self, value, message=None):
        if message is None:
            with self.assertRaises(MetadataValidationError):
                validate_bundle(value)
        else:
            with self.assertRaisesRegex(MetadataValidationError, message):
                validate_bundle(value)

    def test_examples_and_utf8_round_trip(self):
        for value in (self.segmented, self.recognized):
            validate_bundle(value)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "metadata.json"
                write_json(path, value)
                self.assertEqual(read_json(path), value)
        self.assertIn("Học máy", self.recognized["lines"][0]["text"])

    def test_each_entry_schema_and_local_references(self):
        validate_structure("page_metadata", self.segmented["pages"][0])
        validate_structure("line_metadata", self.segmented["lines"][0])
        validate_structure("recognized_line", self.recognized["lines"][0])
        validate_structure("metadata_bundle", self.recognized)

    def test_ids_can_repeat_on_different_pages(self):
        first, last = self.segmented["lines"][0], self.segmented["lines"][-1]
        self.assertEqual(first["line_id"], last["line_id"])
        self.assertNotEqual(line_key(first), line_key(last))
        self.assertEqual(line_key(first), line_key(line_ref(first)))
        validate_bundle(self.segmented)

    def test_unordered_input_is_valid_and_not_modified(self):
        self.recognized["pages"].reverse()
        self.recognized["lines"].reverse()
        original = deepcopy(self.recognized)
        validate_bundle(self.recognized)
        self.assertEqual(self.recognized, original)

    def test_missing_fields_unknown_fields_and_versions(self):
        for target, field, value in [
            ("bundle", "schema_version", 2), ("page", "extra", 1),
            ("line", "extra", 1), ("line", "schema_version", 2),
        ]:
            with self.subTest(target=target, field=field):
                data = deepcopy(self.segmented)
                record = data if target == "bundle" else data["pages" if target == "page" else "lines"][0]
                record[field] = value
                self.assert_invalid(data)
        for target, field in [("bundle", "stage"), ("page", "processed_size"), ("line", "line_id")]:
            data = deepcopy(self.segmented)
            record = data if target == "bundle" else data["pages" if target == "page" else "lines"][0]
            del record[field]
            self.assert_invalid(data)

    def test_integer_fields_reject_bool_and_float(self):
        for field, invalid in [("reading_order", True), ("reading_order", 1.0), ("schema_version", True)]:
            data = deepcopy(self.segmented)
            data["lines"][0][field] = invalid
            self.assert_invalid(data)
        for invalid in (False, 1.0):
            data = deepcopy(self.segmented)
            data["pages"][0]["page_index"] = invalid
            self.assert_invalid(data)

    def test_bbox_bounds_area_and_integer_types(self):
        for box in ([0, 0, 801, 10], [0, 0, 10, 1201], [10, 0, 10, 20],
                    [-1, 0, 10, 20], [20, 0, 10, 20], [False, 0, 10, 20],
                    [0.0, 0, 10, 20], [0, 1, 2]):
            with self.subTest(box=box):
                data = deepcopy(self.segmented)
                data["lines"][0]["bbox"] = box
                self.assert_invalid(data)

    def test_exclusive_bbox_can_touch_page_edges(self):
        self.segmented["lines"][0]["bbox"] = [0, 0, 800, 1200]
        validate_bundle(self.segmented)

    def test_duplicate_line_identity_and_crop(self):
        for field in ("line_id", "image_path", "source_detection_id"):
            data = deepcopy(self.segmented)
            data["lines"][1][field] = data["lines"][0][field]
            self.assert_invalid(data)

    def test_duplicate_or_unknown_page_and_wrong_exam(self):
        for collection, index, field, value in [
            ("pages", 1, "page_id", "p01"), ("pages", 0, "exam_id", "other"),
            ("lines", 0, "page_id", "missing"), ("lines", 0, "exam_id", "other"),
        ]:
            data = deepcopy(self.segmented)
            data[collection][index][field] = value
            self.assert_invalid(data)

    def test_page_and_line_order_gaps_or_duplicates(self):
        for collection, index, field, value in [
            ("pages", 1, "page_index", 1), ("pages", 1, "page_index", 4),
            ("lines", 1, "reading_order", 1), ("lines", 1, "reading_order", 3),
        ]:
            data = deepcopy(self.segmented)
            data[collection][index][field] = value
            self.assert_invalid(data)

    def test_invalid_paths_on_page_and_line(self):
        for value in ("../a.png", "/tmp/a.png", "C:/a.png", "a\\b.png", ".",
                      "./a.png", "a//b.png", "a/", "a\n.png", " "):
            for field in ("image_path", "original_image_path", "processed_image_path"):
                data = deepcopy(self.segmented)
                record = data["lines"][0] if field == "image_path" else data["pages"][0]
                record[field] = value
                self.assert_invalid(data)

    def test_singular_non_affine_and_nonfinite_transforms(self):
        for matrix in ([[1, 2, 0], [2, 4, 0], [0, 0, 1]],
                       [[1, 0, 0], [0, 1, 0], [0.1, 0, 1]],
                       [[float("nan"), 0, 0], [0, 1, 0], [0, 0, 1]],
                       [[True, 0, 0], [0, 1, 0], [0, 0, 1]],
                       [[10**400, 0, 0], [0, 1, 0], [0, 0, 1]],
                       [[10**400, 0, 0], [0, 1.0, 0], [0, 0, 1]]):
            data = deepcopy(self.segmented)
            data["pages"][0]["original_to_processed"] = matrix
            self.assert_invalid(data)

    def test_valid_rotation_resize_transform(self):
        self.segmented["pages"][0]["original_to_processed"] = [[0, -0.5, 600], [0.5, 0, 0], [0, 0, 1]]
        validate_bundle(self.segmented)

    def test_blank_page_cannot_have_lines(self):
        self.segmented["pages"][0]["status"] = "blank"
        self.assert_invalid(self.segmented, "blank")

    def test_ok_page_cannot_silently_lose_all_lines(self):
        self.segmented["lines"] = []
        self.assert_invalid(self.segmented, "at least")

    def test_all_blank_document_can_have_no_lines(self):
        self.segmented["lines"] = []
        for page in self.segmented["pages"]:
            page["status"] = "blank"
        validate_bundle(self.segmented)

    def test_stage_controls_line_type(self):
        self.segmented["lines"][0]["text"] = "Unexpected text for this stage"
        self.assert_invalid(self.segmented)
        data = deepcopy(self.recognized)
        del data["lines"][0]["status"]
        self.assert_invalid(data)
        data = deepcopy(self.recognized)
        data["stage"] = "training"
        self.assert_invalid(data)

    def test_ok_ocr_requires_nonblank_text(self):
        for text in ("", "   ", "\t"):
            data = deepcopy(self.recognized)
            data["lines"][0]["text"] = text
            self.assert_invalid(data, "text")

    def test_empty_prediction_is_distinct_from_failure(self):
        line = self.recognized["lines"][-1]
        line["status"] = "empty_prediction"
        validate_bundle(self.recognized)
        line["text"] = " "
        self.assert_invalid(self.recognized, "empty_prediction")

    def test_failed_ocr_can_preserve_diagnostic_text(self):
        self.recognized["lines"][-1]["text"] = "Untrusted partial result"
        validate_bundle(self.recognized)

    def test_failed_and_review_states_require_error_issue(self):
        data = deepcopy(self.recognized)
        data["lines"][-1]["issues"] = []
        self.assert_invalid(data, "severity=error")
        for status in ("failed", "review_required"):
            data = deepcopy(self.segmented)
            data["pages"][0]["status"] = status
            self.assert_invalid(data, "severity=error")
            data["pages"][0]["issues"] = [{
                "code": "PageNeedsReview", "stage": "segmentation", "severity": "error",
                "message": "Page requires review", "refs": [],
            }]
            validate_bundle(data)

    def test_unresolved_or_duplicate_issue_references(self):
        for field, value in (("line_id", "missing"), ("page_id", "missing"), ("exam_id", "other")):
            data = deepcopy(self.recognized)
            data["lines"][-1]["issues"][0]["refs"][0][field] = value
            self.assert_invalid(data, "refs")
        data = deepcopy(self.recognized)
        refs = data["lines"][-1]["issues"][0]["refs"]
        refs.append(deepcopy(refs[0]))
        self.assert_invalid(data, "refs")

    def test_bad_issue_shape_and_hash_format(self):
        data = deepcopy(self.recognized)
        del data["lines"][-1]["issues"][0]["code"]
        self.assert_invalid(data)
        for field in ("original_sha256", "preprocessing_sha256"):
            data = deepcopy(self.segmented)
            data["pages"][0][field] = "not-a-sha256"
            self.assert_invalid(data)

    def test_metadata_extension_is_allowed_but_must_be_json(self):
        self.segmented["metadata"]["model"] = {"name": "demo", "checkpoint": None}
        validate_bundle(self.segmented)
        for value in (float("inf"), (1, 2), {1: "bad key"}):
            data = deepcopy(self.segmented)
            data["metadata"]["invalid"] = value
            self.assert_invalid(data)

    def test_strict_json_rejects_duplicate_keys_numbers_and_unicode(self):
        for text in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}',
                     '{"a":1e999}', '{"a":"\\ud800"}'):
            with self.assertRaises(ValueError):
                loads_json(text)

    def test_path_resolution_uses_explicit_root_and_checks_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "artifacts"
            root.mkdir()
            self.assertEqual(resolve_path(root, "crops/a.png"), root / "crops/a.png")
            outside = Path(directory) / "outside"
            outside.mkdir()
            (root / "link").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                resolve_path(root, "link/a.png")

    def test_cli_valid_and_invalid_inputs(self):
        command = [sys.executable, "-B", "-m", "src.contracts"]
        result = subprocess.run(command + [str(ROOT / "examples/recognized_lines.json")],
                                cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Valid:", result.stdout)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
            result = subprocess.run(command + [str(path)], cwd=ROOT, capture_output=True,
                                    text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 1)
            self.assertIn("Invalid:", result.stderr)


if __name__ == "__main__":
    unittest.main()
