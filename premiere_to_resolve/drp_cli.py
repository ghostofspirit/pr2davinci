from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .direct_drp import DirectDrpError
from .drp_export import export_prproj_to_drp


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a DaVinci Resolve DRP directly from a Premiere Pro project, without launching Resolve."
    )
    parser.add_argument("input", type=Path, help="Native Premiere Pro .prproj file")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Output .drp path")
    args = parser.parse_args()

    if args.input.suffix.lower() != ".prproj":
        parser.error("direct DRP export requires a native .prproj input")
    if args.output.suffix.lower() != ".drp":
        parser.error("output file must use the .drp extension")

    def warning(message: str) -> None:
        print(f"Warning: {message}", file=sys.stderr)

    try:
        print(f"Reading Premiere project: {args.input}")
        print("Building all project timelines and bins into DRP…")
        output = export_prproj_to_drp(args.input, args.output, on_warning=warning)
        print(f"DRP saved: {output}")
        return 0
    except (OSError, DirectDrpError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
