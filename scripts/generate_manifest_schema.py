from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path

from nodrix.manifest_schema import write_manifest_schema


def main() -> None:
    parser = ArgumentParser(
        description="Generate the canonical Nodrix pipeline JSON Schema."
    )
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        default=Path("src/nodrix/schemas/pipeline.schema.json"),
    )
    args = parser.parse_args()
    print(write_manifest_schema(args.output))


if __name__ == "__main__":
    main()
