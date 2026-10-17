"""Validate a metadata bundle JSON file."""

import argparse

from .io import read_json
from .validators import validate_bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="JSON file containing pages, lines, and stage")
    args = parser.parse_args()
    try:
        value = read_json(args.path)
        validate_bundle(value)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Invalid: {error}\n")
    print(f"Valid: {value['stage']}, {len(value['pages'])} pages, {len(value['lines'])} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
