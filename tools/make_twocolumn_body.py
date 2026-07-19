#!/usr/bin/env python3
"""Adapt Pandoc's LaTeX body for an Elsevier 5p two-column proof.

Pandoc emits pipe tables as ``longtable`` environments, which LaTeX forbids
in two-column mode.  For the manuscript's compact tables, a non-breaking
``table*``/``tabular`` representation is both valid and more appropriate.
Figures are likewise promoted to ``figure*`` so labels remain legible.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


LONGTABLE_RE = re.compile(
    r"\\begin\{longtable\}.*?\\end\{longtable\}", re.DOTALL
)


def convert_longtable(block: str) -> str:
    caption = None
    caption_match = re.search(
        r"\\caption\{(.*?)\}\\tabularnewline\s*", block, re.DOTALL
    )
    if caption_match:
        caption = caption_match.group(1)
        block = block[: caption_match.start()] + block[caption_match.end() :]

    # Retain the first header and discard Pandoc's repeated longtable header.
    if "\\endfirsthead" in block:
        before, remainder = block.split("\\endfirsthead", 1)
        _, after = remainder.split("\\endhead", 1)
        block = before + after
    else:
        block = block.replace("\\endhead", "")

    block = block.replace("\\endlastfoot", "")
    block = block.replace("\\begin{longtable}[]", "\\begin{tabular}", 1)
    block = block.replace("\\end{longtable}", "\\end{tabular}", 1)

    pieces = ["\\begin{table*}[t]", "\\centering", "\\footnotesize"]
    if caption:
        pieces.append(f"\\caption{{{caption}}}")
    pieces.extend((block, "\\end{table*}"))
    return "\n".join(pieces)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    text = args.source.read_text(encoding="utf-8")
    text, table_count = LONGTABLE_RE.subn(
        lambda match: convert_longtable(match.group(0)), text
    )
    text = re.sub(r"\\begin\{figure\}(?:\[H\])?", r"\\begin{figure*}[t]", text)
    text = text.replace("\\end{figure}", "\\end{figure*}")
    args.output.write_text(text, encoding="utf-8")
    print(f"converted {table_count} tables; wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
