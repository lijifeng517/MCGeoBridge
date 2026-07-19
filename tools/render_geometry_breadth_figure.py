"""Render the six-panel geometry-breadth figure used in the manuscript.

Three panels use Geant4 views of emitted GDML and three use reproducible flat
orthographic sections reconstructed from source-deck dimensions.  The latter
are deliberately used where opaque outer shells would hide the converted
interior structure.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "doc" / "MCGeoBridge_paper_draft" / "figures"
INK = "#24343d"
FUEL = "#9d3c32"
STEEL = "#6f8794"
GOLD = "#b79046"
FONT_PATH = Path("C:/Windows/Fonts/arial.ttf")
FONT_BOLD_PATH = Path("C:/Windows/Fonts/arialbd.ttf")


def font(size: int, bold: bool = False):
    path = FONT_BOLD_PATH if bold else FONT_PATH
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default()


def fitted_image(
    path: Path,
    size: tuple[int, int],
    crop: tuple[float, float, float, float] | None = None,
) -> Image.Image:
    image = Image.open(path).convert("RGB")
    if crop is not None:
        image = image.crop(tuple(int(value * limit) for value, limit in zip(
            crop, (image.width, image.height, image.width, image.height)
        )))
    image = ImageEnhance.Contrast(image).enhance(0.90)
    return ImageOps.contain(image, size, method=Image.Resampling.LANCZOS)


def paste_center(canvas: Image.Image, image: Image.Image, box: tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = box
    x = x0 + (x1 - x0 - image.width) // 2
    y = y0 + (y1 - y0 - image.height) // 2
    canvas.paste(image, (x, y))


def draw_pwr(size: tuple[int, int]) -> Image.Image:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    n, pitch = 17, 1.25984
    side = min(size) - 40
    scale = side / (n * pitch)
    cx, cy = size[0] / 2, size[1] / 2
    half = n * pitch * scale / 2
    draw.rectangle((cx-half, cy-half, cx+half, cy+half), fill="#eef4f5", outline=INK, width=3)
    for iy in range(n):
        for ix in range(n):
            x, y = cx + (ix - 8) * pitch * scale, cy - (iy - 8) * pitch * scale
            for radius, color in ((0.45720, STEEL), (0.40005, "#f7f3e9"), (0.39218, FUEL)):
                r = radius * scale
                draw.ellipse((x-r, y-r, x+r, y+r), fill=color)
    return image


def draw_tokamak_section(size: tuple[int, int]) -> Image.Image:
    """Draw the exact R-Z radial build from the MontePy tokamak deck."""
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    cx, cy = size[0] / 2, size[1] / 2
    scale = (min(size) - 46) / (2 * 205.0)
    # Descending disks leave the requested annuli visible.  Radii and material
    # roles are taken directly from fusion_tokomak.imcnp.
    layers = [
        (205.0, "#6554a3"),  # magnets
        (200.0, "#f7f7f4"),  # void behind magnets
        (151.0, "#6f8794"),  # breeder can
        (150.0, "#d5a94e"),  # breeder blanket
        (115.0, "#71828a"),  # vacuum vessel
        (114.0, "#a94236"),  # tungsten first wall
        (113.0, "#dcebed"),  # vacuum / plasma chamber
        (1.0, "#e86c4a"),    # source cell
    ]
    for radius, colour in layers:
        r = radius * scale
        draw.ellipse((cx-r, cy-r, cx+r, cy+r), fill=colour, outline=INK, width=2)
    # Axis and major-radius indication make clear that this is one toroidal
    # meridional section, rather than a generic concentric-cylinder model.
    axis_x = 34
    draw.line((axis_x, 35, axis_x, size[1]-35), fill=INK, width=3)
    draw.line((axis_x, cy, cx, cy), fill="#73838a", width=2)
    draw.polygon(((cx, cy), (cx-12, cy-6), (cx-12, cy+6)), fill="#73838a")
    draw.text((axis_x+10, cy-34), "R = 330 cm", font=font(22), fill="#53656e")
    return image


def fridge_fill_values() -> list[int]:
    path = ROOT / "test" / "engineering_cases" / "FRIDGe-1.0.1" / "FRIDGe-1.0.1" / "fridge" / "mcnp_input_files" / "Prefab_Fuel_Assembly_Test.i"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = next(i for i, line in enumerate(lines) if "fill=-10:10 -10:10 0:0" in line)
    tokens: list[int] = []
    for line in lines[start + 1:]:
        if re.match(r"^\s*106\s", line):
            break
        tokens.extend(int(item) for item in re.findall(r"\b10[12]\b", line))
    if len(tokens) != 441:
        raise ValueError(f"expected 441 FRIDGe fill entries, found {len(tokens)}")
    return tokens


def draw_fridge(size: tuple[int, int]) -> Image.Image:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    values = fridge_fill_values()
    scale = min(size[0] / 27, size[1] / 23)
    cx, cy = size[0] / 2, size[1] / 2
    for row in range(21):
        for col in range(21):
            value = values[row * 21 + col]
            qx = (col - 10) + (row - 10) / 2
            qy = (row - 10) * math.sqrt(3) / 2
            x = cx + qx * scale
            y = cy - qy * scale
            in_hex = (
                abs(qy) <= math.sqrt(3) * 11.2 / 2
                and math.sqrt(3) * abs(qx) + abs(qy) <= math.sqrt(3) * 11.2
            )
            if value == 101:
                for radius, color in ((0.39, STEEL), (0.29, GOLD)):
                    r = radius * scale
                    draw.ellipse((x-r, y-r, x+r, y+r), fill=color)
            elif in_hex:
                r = 0.16 * scale
                draw.ellipse((x-r, y-r, x+r, y+r), fill="#c8dde0")
    radius = 11.7 * scale
    vertices = [(cx + radius * math.cos(math.radians(60*k+30)),
                 cy - radius * math.sin(math.radians(60*k+30))) for k in range(6)]
    draw.polygon(vertices, outline=INK, width=5)
    inner = [(cx + 0.96*(x-cx), cy + 0.96*(y-cy)) for x, y in vertices]
    draw.polygon(inner, outline=STEEL, width=3)
    return image


def case17_radii() -> list[float]:
    text = (ROOT / "test" / "CASE_17").read_text(encoding="utf-8", errors="replace")
    radii = []
    for number, radius in re.findall(r"(?mi)^\s*(\d+)\s+So\s+([0-9.]+)", text):
        if 85 <= int(number) <= 165:
            radii.append(float(radius))
    return radii


def draw_case17(size: tuple[int, int]) -> Image.Image:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    radii = case17_radii()
    scale = min((size[0]-55) / max(radii), (size[1]-30) / (2*max(radii)))
    ox, oy = 35, size[1] / 2
    for index in range(len(radii)-1, -1, -1):
        radius = radii[index] * scale
        if index < 56:
            color = "#d4dcdf" if index % 2 == 0 else "#75868e"
        else:
            color = "#d0ab60" if index % 2 == 0 else "#8b6a2f"
        box = (ox-radius, oy-radius, ox+radius, oy+radius)
        draw.pieslice(box, start=-90, end=90, fill=color, outline=INK, width=1)
    # Axial pole hole: CX 0.35687, shown in the x-z section.
    hole = 0.35687 * scale
    draw.rectangle((ox, oy-hole, ox+max(radii)*scale, oy+hole), fill="white", outline=INK, width=2)
    draw.line((ox, oy-max(radii)*scale, ox, oy+max(radii)*scale), fill=INK, width=3)
    return image


def label(draw: ImageDraw.ImageDraw, box, letter: str, title: str, feature: str) -> None:
    x0, y0, x1, y1 = box
    draw.rounded_rectangle((x0+7, y0+7, x0+60, y0+51), radius=4, fill="white")
    draw.text((x0+14, y0+10), f"({letter})", font=font(27, True), fill=INK)
    center = (x0+x1)//2
    title_font, feature_font = font(29, True), font(23)
    title_box = draw.textbbox((0, 0), title, font=title_font)
    feature_box = draw.textbbox((0, 0), feature, font=feature_font)
    draw.text((center-(title_box[2]-title_box[0])//2, y1+10), title, font=title_font, fill=INK)
    draw.text((center-(feature_box[2]-feature_box[0])//2, y1+49), feature, font=feature_font, fill="#53656e")


def main() -> None:
    width, height = 2400, 1660
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    margin, gap = 48, 42
    panel_w = (width - 2*margin - 2*gap) // 3
    view_h = 610
    rows_y = (42, 855)
    boxes = []
    for y in rows_y:
        for col in range(3):
            x = margin + col*(panel_w+gap)
            boxes.append((x, y, x+panel_w, y+view_h))

    paste_center(
        canvas,
        fitted_image(ROOT / "tmp" / "0005_elite_paper.jpeg", (panel_w, view_h)),
        boxes[0],
    )
    paste_center(
        canvas,
        fitted_image(
            ROOT / "tmp" / "mccad_hires_volume_raw.jpeg",
            (panel_w, view_h),
            crop=(0.36, 0.12, 0.70, 0.60),
        ),
        boxes[1],
    )
    paste_center(canvas, draw_tokamak_section((panel_w, view_h)), boxes[2])
    for image, box in zip(
        (draw_pwr((panel_w, view_h)), draw_fridge((panel_w, view_h)), draw_case17((panel_w, view_h))),
        boxes[3:],
    ):
        paste_center(canvas, image, box)

    labels = [
        ("a", "E-Lite sector model", "nested unions and sector partitions"),
        ("b", "McCAD component library", "mixed primitives and placements"),
        ("c", "Tokamak radial section", "nested toroidal material layers"),
        ("d", "PWR 17×17 assembly", "LAT=1 square repeated structure"),
        ("e", "FRIDGe fuel assembly", "LAT=2 indexed hexagonal fill"),
        ("f", "Hemishell critical assembly", "HMF-048 Case 17 · U/steel shell stack"),
    ]
    for box, args in zip(boxes, labels):
        label(draw, box, *args)

    OUT.mkdir(parents=True, exist_ok=True)
    png = OUT / "fig_geometry_breadth.png"
    pdf = OUT / "fig_geometry_breadth.pdf"
    canvas.save(png, dpi=(400, 400), optimize=True)
    canvas.save(pdf, "PDF", resolution=400.0)
    print(png)
    print(pdf)


if __name__ == "__main__":
    main()
