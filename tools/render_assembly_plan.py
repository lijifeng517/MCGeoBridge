"""Render an orthographic XY plan for the public spent-fuel 17x17 lattice."""

from pathlib import Path


def main() -> None:
    pitch = 1.25984
    n = 17
    center = (n - 1) / 2
    canvas = 1100
    margin = 90
    extent = n * pitch
    scale = (canvas - 2 * margin) / extent

    def xy(ix: int, iy: int) -> tuple[float, float]:
        return (
            canvas / 2 + (ix - center) * pitch * scale,
            canvas / 2 - (iy - center) * pitch * scale,
        )

    circles = []
    for iy in range(n):
        for ix in range(n):
            cx, cy = xy(ix, iy)
            # Outer zirconium cladding, annular gap, and UO2 fuel pellet.
            circles.append(
                f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{0.45720 * scale:.2f}" '
                'fill="#6f8794" stroke="#34515e" stroke-width="1"/>'
            )
            circles.append(
                f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{0.40005 * scale:.2f}" '
                'fill="#f4f0e8"/>'
            )
            circles.append(
                f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{0.39218 * scale:.2f}" '
                'fill="#9d3c32"/>'
            )

    half = extent * scale / 2
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{canvas}" height="{canvas}" viewBox="0 0 {canvas} {canvas}">
  <rect width="100%" height="100%" fill="#ffffff"/>
  <rect x="{canvas/2-half:.2f}" y="{canvas/2-half:.2f}" width="{2*half:.2f}" height="{2*half:.2f}" fill="#eaf2f5" stroke="#34515e" stroke-width="4"/>
  {''.join(circles)}
  <g font-family="Arial, sans-serif" font-size="24" fill="#24343d">
    <text x="{margin}" y="{canvas-35}">17×17 fuel-pin lattice · orthographic XY section</text>
  </g>
  <g font-family="Arial, sans-serif" font-size="20" fill="#24343d">
    <circle cx="{canvas-390}" cy="{canvas-43}" r="11" fill="#9d3c32"/><text x="{canvas-370}" y="{canvas-35}">fuel</text>
    <circle cx="{canvas-265}" cy="{canvas-43}" r="11" fill="#6f8794"/><text x="{canvas-245}" y="{canvas-35}">cladding</text>
  </g>
</svg>'''
    target = Path("tmp/spentfuel_single_assembly_orthographic.svg")
    target.write_text(svg, encoding="utf-8")

    # Complementary three-scale plate: lattice, axial pin section, and four
    # translated assemblies inside the canister basket.  It is an orthographic
    # drawing from the same public MCNP geometry parameters, not a transport plot.
    W, H = 1560, 620
    panel_w, gap, left = 450, 45, 60
    circles_small = []
    mini_pitch, mini_r = 18, 6.5
    for iy in range(17):
        for ix in range(17):
            cx = left + 225 + (ix - 8) * mini_pitch
            cy = 330 - (iy - 8) * mini_pitch
            circles_small.append(f'<circle cx="{cx}" cy="{cy}" r="{mini_r+2}" fill="#6f8794"/>')
            circles_small.append(f'<circle cx="{cx}" cy="{cy}" r="{mini_r}" fill="#9d3c32"/>')

    basket_x = left + 2 * (panel_w + gap) + 225
    mini_assemblies = []
    for ox, oy in ((-92, -92), (-92, 92), (92, -92), (92, 92)):
        for iy in range(7):
            for ix in range(7):
                cx = basket_x + ox + (ix - 3) * 10
                cy = 330 + oy - (iy - 3) * 10
                mini_assemblies.append(f'<circle cx="{cx}" cy="{cy}" r="4" fill="#9d3c32"/>')
        mini_assemblies.append(f'<rect x="{basket_x+ox-39}" y="{330+oy-39}" width="78" height="78" fill="none" stroke="#6f8794" stroke-width="4"/>')

    plate = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <rect width="100%" height="100%" fill="#fff"/>
  <g font-family="Arial, sans-serif" fill="#24343d">
    <text x="60" y="55" font-size="30">Public spent-fuel MCNP model: geometry conversion evidence</text>
    <text x="60" y="100" font-size="22">(a) 17×17 lattice</text>
    <text x="555" y="100" font-size="22">(b) axial fuel-pin section</text>
    <text x="1050" y="100" font-size="22">(c) four-assembly basket layout</text>
  </g>
  <line x1="510" y1="80" x2="510" y2="560" stroke="#c8d3d8" stroke-width="2"/>
  <line x1="1005" y1="80" x2="1005" y2="560" stroke="#c8d3d8" stroke-width="2"/>
  <rect x="{left+72}" y="177" width="306" height="306" fill="#eaf2f5" stroke="#34515e" stroke-width="3"/>
  {''.join(circles_small)}
  <g>
    <rect x="670" y="145" width="110" height="375" rx="8" fill="#6f8794" stroke="#34515e" stroke-width="3"/>
    <rect x="686" y="160" width="78" height="345" rx="5" fill="#f4f0e8"/>
    <rect x="694" y="170" width="62" height="325" rx="4" fill="#9d3c32"/>
    <rect x="650" y="255" width="150" height="18" fill="#466b77"/>
    <rect x="650" y="390" width="150" height="18" fill="#466b77"/>
    <line x1="810" y1="190" x2="865" y2="190" stroke="#9d3c32" stroke-width="2"/><text x="875" y="197" font-family="Arial" font-size="18">fuel</text>
    <line x1="810" y1="225" x2="865" y2="225" stroke="#6f8794" stroke-width="2"/><text x="875" y="232" font-family="Arial" font-size="18">cladding</text>
    <line x1="810" y1="264" x2="865" y2="264" stroke="#466b77" stroke-width="2"/><text x="875" y="271" font-family="Arial" font-size="18">spacer grid</text>
  </g>
  <g>
    <circle cx="{basket_x}" cy="330" r="188" fill="#e9eee9" stroke="#466b77" stroke-width="16"/>
    <circle cx="{basket_x}" cy="330" r="153" fill="#fff" stroke="#b8a47b" stroke-width="11"/>
    {''.join(mini_assemblies)}
  </g>
  <g font-family="Arial, sans-serif" font-size="18" fill="#24343d">
    <circle cx="80" cy="570" r="9" fill="#9d3c32"/><text x="96" y="576">fuel</text>
    <circle cx="175" cy="570" r="9" fill="#6f8794"/><text x="191" y="576">cladding</text>
    <rect x="305" y="561" width="18" height="18" fill="#466b77"/><text x="331" y="576">structural steel</text>
  </g>
</svg>'''
    Path("tmp/spentfuel_geometry_evidence_plate.svg").write_text(plate, encoding="utf-8")


if __name__ == "__main__":
    main()
