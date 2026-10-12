from __future__ import annotations

import argparse
from pathlib import Path

from .converter import ConversionError, convert_project, list_sequences


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert a Premiere .prproj XML project to Resolve-importable FCP 7 XML.")
    parser.add_argument("input", type=Path, help="Premiere .prproj XML file")
    parser.add_argument("-o", "--output", type=Path, help="Output FCP XML path")
    parser.add_argument("--sequence", help="Exact Premiere sequence name; defaults to the first sequence")
    parser.add_argument("--list-sequences", action="store_true", help="List sequences and exit")
    args = parser.parse_args()
    try:
        if args.list_sequences:
            for name in list_sequences(args.input):
                print(name)
            return 0
        if args.output is None:
            parser.error("--output is required unless --list-sequences is used")
        name = convert_project(args.input, args.output, args.sequence)
        print(f"Converted {name!r} to {args.output}")
        return 0
    except (OSError, ConversionError) as error:
        parser.error(str(error))
        return 2
