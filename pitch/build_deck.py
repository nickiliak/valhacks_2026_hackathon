"""Build the two-slide shareholder pitch: pitch/hotel_booking_pitch.pptx.

uv run --with python-pptx python pitch/build_deck.py

Figures come from artifacts/simulate_q4_development/summary.csv (October-December
2016 replay of the final version) and the proven hindsight optimum recorded in
the README. To show the official score, edit the "Official result" text on
slide 2 in PowerPoint, or change OFFICIAL_RESULT below and rebuild.
"""

from io import BytesIO
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

OUTPUT = Path(__file__).with_name("hotel_booking_pitch.pptx")
OFFICIAL_RESULT = "Awaiting official evaluation"   # replace with e.g. "€12.3M net revenue"

INK, INK_TILE = "0F2F33", "1B4649"       # deep green-teal: the dominant colour
GOLD, GOLD_DARK = "E3A72F", "9A6B0C"     # accent; darker shade for small text on white
CORAL = "F2907A"                         # relocation cost, on dark
MINT, LINE = "EAF2F0", "CBD9D6"          # card tint and hairlines
TEXT, MUTED, ON_DARK = "14282B", "566769", "C9DCD9"
BAR, HINDSIGHT = "B5C2C1", "86ADA8"
HEAD, BODY = "Cambria", "Calibri"
_GROUP = [None]   # animation group of the shapes being created; add_animations.ps1 reveals a group together


def group(name) -> None:
    _GROUP[0] = name


def tag(shape, name=None):
    """Name a shape. Shapes of one animation group share the prefix "<group>#"."""
    if _GROUP[0]:
        shape.name = f"{_GROUP[0]}#{name or shape.shape_id}"
    elif name:
        shape.name = name
    return shape

SCRIPT_1 = """A hotel can have a full reservation book and still have empty rooms, because some guests cancel and others never arrive. But accept every reservation and you get the opposite problem: guests arrive and there is nowhere to put them.

Under this challenge's rules, a stay worth 100 euros earns 100 euros if we give the guest a room. If the hotel is full and we have to relocate them, we earn nothing and pay 250. So the question is not how to fill the hotel. It is which bookings to say yes to.

[CLICK] We studied more than 78,000 past bookings from two hotels. Guests who book at the last minute almost always arrive; most of those who book a year ahead cancel.

So for every request we ask three questions.

[CLICK] First: who will actually arrive? A model trained on those past bookings gives each booking a chance of showing up.

[CLICK] Second: what is the room worth? For every night we look at what the guests who booked later paid last year. If higher-paying guests are still likely to book, we hold the room for them.

[CLICK] Third: does saying yes pay off? We cannot know who will turn up, so we rehearse the night 200 times on the computer. In each rehearsal some guests arrive and some do not, according to their chances. We add up the money with this booking and without it.

[CLICK] Here is a real request: two nights at 119 euros a night. We gave this guest a 72% chance of arriving. The minimum price for those nights was 91 euros, so the price was fine. In the rehearsals the booking brought in 170 euros on average, and added 109 euros of relocation risk, because the hotel was nearly full. That leaves the hotel 61 euros better off, so we accepted. The guest did stay.

The hotel still sets its prices; our system only decides which requests to accept. And we never refuse someone just because they might cancel: a cancellation costs nothing."""

SCRIPT_2 = """What did those decisions deliver? We replayed October to December 2016, booking by booking, under the competition's rules.

[CLICK] Accepting every booking almost wipes out the income: relocation costs eat nearly all of it. Never overbooking is safe but leaves rooms empty: 0.79 million euros. Standard overbooking accepts extra bookings up to each hotel's usual share of no-shows, treating every guest alike. It earns 1.07 million.

[CLICK] Our system earns 1.35 million. For every 100 euros the standard approach makes, ours makes 126. And it relocates a third fewer guests: 288 instead of 436.

A manager who knew in advance exactly who would cancel could have earned about 1.63 million. We reach 83% of that without knowing the future.

Two honest notes. These figures come from our own replay of past bookings, not the official test. And we had already studied these months when we made our last improvements; an earlier version, tested once on months it had never seen, was 18% ahead of standard overbooking.

[If the official score is known: On the organisers' 2017 test, our solution scored ... ]

For a shareholder, this is more income from rooms the hotels already have, with fewer guests let down. For a hotel manager, every decision comes with a reason they can read.

Same rooms. Better decisions."""


def rgb(value: str) -> RGBColor:
    return RGBColor.from_string(value)


def box(slide, x, y, w, h, fill, *, radius=None, line=None, name=None):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
                                   Inches(x), Inches(y), Inches(w), Inches(h))
    if radius:
        shape.adjustments[0] = radius
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(fill)
    if line:
        shape.line.color.rgb = rgb(line)
        shape.line.width = Pt(1)
    else:
        shape.line.fill.background()
    shape.shadow.inherit = False
    return tag(shape, name)


def text(slide, x, y, w, h, paragraphs, *, size=14, color=TEXT, bold=False, font=BODY, align=PP_ALIGN.LEFT,
         anchor=MSO_ANCHOR.TOP, spacing=None, line_spacing=None, name=None):
    """paragraphs: a string, or a list of paragraphs; a paragraph is a string or a list of (text, overrides)."""
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = shape.text_frame
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    frame.vertical_anchor = anchor
    if isinstance(paragraphs, str):
        paragraphs = [paragraphs]
    for index, runs in enumerate(paragraphs):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.alignment = align
        if line_spacing:
            paragraph.line_spacing = line_spacing
        for content, overrides in ([(runs, {})] if isinstance(runs, str) else runs):
            run = paragraph.add_run()
            run.text = content
            style = {"size": size, "color": color, "bold": bold, "font": font, **overrides}
            run.font.size = Pt(style["size"])
            run.font.bold = style["bold"]
            run.font.name = style["font"]
            run.font.color.rgb = rgb(style["color"])
            if spacing:
                run.font._element.set("spc", str(spacing))
    return tag(shape, name)


def icon(slide, glyph: int, x, y, size, color="FFFFFF"):
    """A Windows icon-font glyph drawn to a transparent PNG, so the deck needs no special font."""
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/segmdl2.ttf", 220)
    except OSError:
        return
    image = Image.new("RGBA", (320, 320), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = draw.textbbox((0, 0), chr(glyph), font=font)
    draw.text(((320 - (right - left)) / 2 - left, (320 - (bottom - top)) / 2 - top), chr(glyph), font=font,
              fill=tuple(int(color[i:i + 2], 16) for i in (0, 2, 4)) + (255,))
    buffer = BytesIO()
    image.save(buffer, "PNG")
    buffer.seek(0)
    tag(slide.shapes.add_picture(buffer, Inches(x), Inches(y), Inches(size), Inches(size)), "icon")


def slide_one(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box(slide, 0, 0, 4.75, 7.5, INK, name="Dark panel")
    text(slide, 0.6, 0.62, 3.7, 0.3, "HOTEL BOOKING DECISIONS", size=11, color=GOLD, bold=True, spacing=150)
    text(slide, 0.6, 1.05, 3.75, 2.0, "Earn more from the rooms we already have", size=33, color="FFFFFF", bold=True,
         font=HEAD, line_spacing=0.95, name="Title")
    text(slide, 0.6, 3.1, 3.6, 0.8, "Empty rooms lose income. No room for an arriving guest costs even more.",
         size=15, color=ON_DARK)
    for y, amount, colour, caption in [(4.15, "+€100", "FFFFFF", "earned when a guest gets their room"),
                                       (5.4, "−€250", CORAL, "lost when the hotel is full and we relocate them")]:
        group("s1-tile1" if y < 5 else "s1-tile2")
        box(slide, 0.6, y, 3.6, 1.05, INK_TILE, radius=0.12)
        text(slide, 0.82, y, 1.55, 1.05, amount, size=30, color=colour, bold=True, font=HEAD, anchor=MSO_ANCHOR.MIDDLE)
        text(slide, 2.35, y, 1.7, 1.05, caption, size=13, color=ON_DARK, anchor=MSO_ANCHOR.MIDDLE)
    group(None)
    text(slide, 0.6, 6.68, 3.6, 0.3, "For a €100 stay, under the competition rules", size=11, color="9DB7B3")

    group("s1-heading")
    text(slide, 5.25, 0.6, 7.5, 0.5, "Three questions for every booking request", size=24, bold=True, font=HEAD)
    text(slide, 5.25, 1.15, 7.5, 0.3, "Learned from 78,132 past bookings at two hotels", size=14, color=MUTED)
    cards = [(0xE77B, "Who will actually arrive?", "Each booking gets a show-up chance from how and when it was made."),
             (0xE8EC, "What is the room worth?", "Each night gets a minimum price from what late bookers paid last year."),
             (0xE8AB, "Does saying yes pay off?", "We rehearse the night 200 times, with and without the booking.")]
    for index, (glyph, question, answer) in enumerate(cards):
        x = 5.25 + index * 2.6
        group(f"s1-card{index + 1}")
        box(slide, x, 1.75, 2.3, 3.1, MINT, radius=0.07, name=f"Question {index + 1}")
        circle = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x + 0.25), Inches(2.0), Inches(0.72), Inches(0.72))
        circle.fill.solid()
        circle.fill.fore_color.rgb = rgb(INK)
        circle.line.fill.background()
        circle.shadow.inherit = False
        tag(circle, "icon circle")
        icon(slide, glyph, x + 0.25 + 0.17, 2.0 + 0.17, 0.38)
        text(slide, x + 0.25, 2.92, 1.85, 0.7, question, size=18, bold=True, font=HEAD, line_spacing=0.95)
        text(slide, x + 0.25, 3.68, 1.85, 1.05, answer, size=14, color=MUTED)
        if index < 2:
            group(f"s1-card{index + 2}")   # the arrow arrives with the next question
            text(slide, x + 2.3, 3.05, 0.3, 0.5, "›", size=26, color=GOLD, bold=True, align=PP_ALIGN.CENTER,
                 anchor=MSO_ANCHOR.MIDDLE)

    group("s1-example")
    box(slide, 5.25, 5.15, 7.5, 1.78, "FFFFFF", radius=0.08, line=LINE, name="Example")
    text(slide, 5.5, 5.3, 7.0, 0.25, "A REAL REQUEST: TWO NIGHTS AT €119 A NIGHT", size=11, color=GOLD_DARK, bold=True, spacing=150)
    # Booking 99512 in artifacts/simulate_q4_development/stay_value_decisions.csv, one chip per question.
    chips = [(1.35, "72%", "likely to arrive", MINT, TEXT, MUTED),
             (1.35, "€91", "minimum price that night", MINT, TEXT, MUTED),
             (2.1, "+€61", "€170 expected income, €109 relocation risk", MINT, TEXT, MUTED),
             (1.6, "Accepted", "and the guest stayed", INK, GOLD, "FFFFFF")]
    x = 5.5
    for index, (width, value, caption, fill, value_colour, caption_colour) in enumerate(chips):
        group(f"s1-chip{index + 1}")
        box(slide, x, 5.68, width, 1.02, fill, radius=0.14)
        text(slide, x + 0.15, 5.76, width - 0.3, 0.45, value, size=21, color=value_colour, bold=True, font=HEAD,
             anchor=MSO_ANCHOR.MIDDLE)
        text(slide, x + 0.15, 6.22, width - 0.3, 0.4, caption, size=11.5, color=caption_colour)
        if index < 3:
            group(f"s1-chip{index + 2}")
            text(slide, x + width, 5.68, 0.2, 1.02, "›", size=20, color=GOLD, bold=True, align=PP_ALIGN.CENTER,
                 anchor=MSO_ANCHOR.MIDDLE)
        x += width + 0.2
    group(None)
    slide.notes_slide.notes_text_frame.text = SCRIPT_1


def slide_two(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    text(slide, 0.6, 0.62, 7.6, 0.3, "WHAT THOSE DECISIONS DELIVERED", size=11, color=GOLD_DARK, bold=True, spacing=150)
    text(slide, 0.6, 1.0, 7.7, 1.25, "Same rooms, better decisions: 26% more net revenue", size=31, bold=True, font=HEAD,
         line_spacing=0.95, name="Title")
    text(slide, 0.6, 2.38, 7.6, 0.3, "Net revenue after relocation costs, October–December 2016", size=14, color=MUTED)

    data = CategoryChartData()
    rows = [("Accept every booking", 0.04, BAR), ("Never overbook", 0.79, BAR), ("Standard overbooking", 1.07, BAR),
            ("Our system", 1.35, GOLD), ("Perfect hindsight", 1.63, HINDSIGHT)]
    data.categories = [name for name, _, _ in rows]
    data.add_series("Net revenue, € million", [value for _, value, _ in rows])
    group("s2-chart")
    frame = slide.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(0.45), Inches(2.72), Inches(7.9), Inches(3.05), data)
    tag(frame, "Net revenue chart")
    group(None)
    chart = frame.chart
    chart.has_legend = False
    chart.has_title = False
    chart.font.name = BODY
    chart.font.size = Pt(14)
    chart.font.color.rgb = rgb(TEXT)
    plot = chart.plots[0]
    plot.gap_width = 45
    plot.vary_by_categories = False
    for point, (_, _, colour) in zip(plot.series[0].points, rows):
        point.format.fill.solid()
        point.format.fill.fore_color.rgb = rgb(colour)
    plot.has_data_labels = True
    labels = plot.data_labels
    labels.number_format = '"€"0.00"M"'
    labels.number_format_is_linked = False
    labels.position = XL_LABEL_POSITION.OUTSIDE_END
    labels.font.size = Pt(14)
    labels.font.bold = True
    labels.font.color.rgb = rgb(TEXT)
    chart.category_axis.reverse_order = True
    chart.category_axis.format.line.color.rgb = rgb(LINE)
    chart.category_axis.has_major_gridlines = False
    chart.category_axis.tick_labels.font.size = Pt(14)
    chart.value_axis.visible = False
    chart.value_axis.has_major_gridlines = False
    chart.value_axis.minimum_scale = 0
    chart.value_axis.maximum_scale = 1.95

    text(slide, 0.6, 5.88, 7.7, 0.5,
         [[("Standard overbooking", {"bold": True, "color": TEXT}),
           (" accepts extra bookings up to each hotel's usual share of no-shows, treating every guest alike. ", {}),
           ("Perfect hindsight", {"bold": True, "color": TEXT}),
           (" knows in advance who will cancel.", {})]], size=12, color=MUTED)
    text(slide, 0.6, 6.55, 7.7, 0.5,
         "Replay of real bookings using our reconstruction of the competition scoring: a development result, not the "
         "official score. An earlier frozen version, tested once on months it had never seen, earned €1.26M (+18%).",
         size=10.5, color=MUTED)

    box(slide, 8.75, 0, 4.583, 7.5, INK, name="Dark panel")
    box(slide, 9.15, 0.6, 3.75, 1.5, INK_TILE, radius=0.1, name="Official result tile")
    text(slide, 9.4, 0.8, 3.3, 0.25, "OFFICIAL 2017 TEST", size=11, color=GOLD, bold=True, spacing=150)
    text(slide, 9.4, 1.12, 3.3, 0.8, OFFICIAL_RESULT, size=20, color="FFFFFF", bold=True, font=HEAD,
         anchor=MSO_ANCHOR.MIDDLE, name="Official result")
    text(slide, 9.15, 2.5, 3.75, 0.25, "ON PAST BOOKINGS, OCTOBER–DECEMBER 2016", size=10.5, color="9DB7B3", bold=True,
         spacing=100)
    stats = [("+26%", "more net revenue than standard overbooking"),
             ("34%", "fewer guests relocated: 288 instead of 436"),
             ("83%", "of what perfect hindsight would earn")]
    for index, (value, caption) in enumerate(stats):
        y = 2.9 + index * 1.38
        group(f"s2-stat{index + 1}")
        text(slide, 9.15, y, 3.75, 0.72, value, size=44, color=GOLD, bold=True, font=HEAD, anchor=MSO_ANCHOR.MIDDLE)
        text(slide, 9.15, y + 0.74, 3.75, 0.5, caption, size=14, color=ON_DARK)
    group(None)
    slide.notes_slide.notes_text_frame.text = SCRIPT_2


def main() -> None:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    prs.core_properties.title = "Hotel booking decisions: earn more from the rooms we already have"
    prs.core_properties.author = "Valhacks 2026 team"
    slide_one(prs)
    slide_two(prs)
    prs.save(OUTPUT)
    print(f"wrote {OUTPUT}")
    animate()


def animate() -> None:
    """Add click-by-click reveals with the installed PowerPoint. Without it the deck is simply static."""
    script = Path(__file__).with_name("add_animations.ps1")
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                                 "-Deck", str(OUTPUT)], capture_output=True, text=True, timeout=180)
        print(result.stdout.strip() if result.returncode == 0 else f"animations skipped: {result.stderr.strip()[:400]}")
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"animations skipped: {error}")


if __name__ == "__main__":
    main()
