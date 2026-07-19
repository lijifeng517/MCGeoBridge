#!/usr/bin/env python3
"""Reframe a white-background renderer image without changing canvas size."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageChops


def reframe(source: Path, destination: Path, occupancy: float, threshold: int) -> None:
    with Image.open(source) as opened:
        image = opened.convert("RGB")
    width, height = image.size
    background = Image.new("RGB", image.size, image.getpixel((0, 0)))
    difference = ImageChops.difference(image, background).convert("L")
    mask = difference.point(lambda value: 255 if value > threshold else 0)
    bounds = mask.getbbox()
    if bounds is None:
        raise ValueError(f"no foreground pixels detected in {source}")

    foreground = image.crop(bounds)
    scale = min(
        occupancy * width / foreground.width,
        occupancy * height / foreground.height,
    )
    resized = foreground.resize(
        (max(1, round(foreground.width * scale)),
         max(1, round(foreground.height * scale))),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGB", image.size, (255, 255, 255))
    position = ((width - resized.width) // 2, (height - resized.height) // 2)
    canvas.paste(resized, position)
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, quality=95, subsampling=0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--occupancy", type=float, default=0.86)
    parser.add_argument("--threshold", type=int, default=8)
    arguments = parser.parse_args()
    if not 0.1 <= arguments.occupancy <= 1.0:
        parser.error("--occupancy must be between 0.1 and 1.0")
    if not 0 <= arguments.threshold <= 255:
        parser.error("--threshold must be between 0 and 255")
    reframe(
        arguments.source,
        arguments.destination,
        arguments.occupancy,
        arguments.threshold,
    )


if __name__ == "__main__":
    main()
