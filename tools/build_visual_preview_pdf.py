"""Build a compact PDF preview of the manuscript visualization section."""

from pathlib import Path

from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer


ROOT = Path(__file__).resolve().parents[1]
FIGURES = ROOT / "doc" / "MCGeoBridge_paper_draft" / "figures"
OUTPUT = ROOT / "output" / "pdf" / "MCGeoBridge_visualization_preview.pdf"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "PreviewTitle", parent=styles["Title"], alignment=TA_CENTER, fontSize=16, leading=20
    )
    caption = ParagraphStyle(
        "Caption", parent=styles["BodyText"], fontSize=9, leading=12, spaceAfter=10
    )
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=10, leading=14)
    document = SimpleDocTemplate(
        str(OUTPUT), pagesize=A4, rightMargin=2.0 * cm, leftMargin=2.0 * cm,
        topMargin=1.8 * cm, bottomMargin=1.8 * cm,
    )
    story = [
        Paragraph("MCGeoBridge manuscript - visualization preview", title),
        Spacer(1, 0.3 * cm),
        Paragraph(
            "This preview verifies the two Geant4 off-screen renderings inserted in the "
            "manuscript section <i>Geant4 Visualization Checks</i>. The images are "
            "qualitative geometry-inspection evidence, not transport-equivalence results.",
            body,
        ),
        Spacer(1, 0.35 * cm),
    ]
    for filename, text in (
        (
            "fig3_elite_geant4.jpeg",
            "Figure 3. Converted F4Enix E-Lite fusion-sector model rendered by Geant4. "
            "The view exposes non-uniform angular sectors and nested radial regions.",
        ),
        (
            "fig4_tokamak_geant4.jpeg",
            "Figure 4. Converted simplified tokamak radial-build model rendered by Geant4. "
            "This is a focused nested-TZ and Boolean-cell syntax example.",
        ),
    ):
        image = Image(str(FIGURES / filename))
        image._restrictSize(16.0 * cm, 10.0 * cm)
        image.hAlign = "CENTER"
        story.extend([image, Spacer(1, 0.12 * cm), Paragraph(text, caption), Spacer(1, 0.18 * cm)])
    document.build(story)
    print(OUTPUT)


if __name__ == "__main__":
    main()
