"""Command line: python -m firb_tracer STRUCTURE.yaml [-o REPORT.md]"""

import argparse
import sys
from pathlib import Path

from .model import InputError, load_yaml
from .report import render_markdown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="firb_tracer",
        description="Screen a structure under Australia's foreign government investor rules.",
    )
    parser.add_argument("structure", help="a YAML file describing the structure and transaction")
    parser.add_argument("-o", "--output", help="write the report to this Markdown file instead of the screen")
    args = parser.parse_args(argv)

    try:
        report = render_markdown(load_yaml(args.structure))
    except (InputError, ValueError) as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 1

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"Report written to {args.output}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
