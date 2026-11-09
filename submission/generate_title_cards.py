"""
submission/generate_title_cards.py
────────────────────────────────────────────────────────────────────────────────
Generates 1920x1080 graphic frames for title, architecture, and closing scenes.
Uses PIL with sleek dark-mode styling matching LedgerMind's UI.
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

FRAMES_DIR = Path(r"C:\Users\kiran\LedgerMind\submission\video\frames")
FRAMES_DIR.mkdir(parents=True, exist_ok=True)

WIDTH = 1920
HEIGHT = 1080

def get_font(size: int, bold: bool = False):
    font_names = [
        "C:\\Windows\\Fonts\\segoeuib.ttf" if bold else "C:\\Windows\\Fonts\\segoeui.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf" if bold else "C:\\Windows\\Fonts\\arial.ttf",
    ]
    for fn in font_names:
        if Path(fn).exists():
            try:
                return ImageFont.truetype(fn, size)
            except Exception:
                pass
    return ImageFont.load_default()

def draw_gradient_background(draw, width, height, top_color, bottom_color):
    for y in range(height):
        r = int(top_color[0] + (bottom_color[0] - top_color[0]) * (y / height))
        g = int(top_color[1] + (bottom_color[1] - top_color[1]) * (y / height))
        b = int(top_color[2] + (bottom_color[2] - top_color[2]) * (y / height))
        draw.line([(0, y), (width, y)], fill=(r, g, b))

def create_title_card():
    img = Image.new("RGB", (WIDTH, HEIGHT), color=(11, 15, 25))
    draw = ImageDraw.Draw(img)
    draw_gradient_background(draw, WIDTH, HEIGHT, (9, 13, 24), (17, 24, 39))

    # Glow accents / decorative borders
    draw.rounded_rectangle([160, 120, WIDTH - 160, HEIGHT - 120], radius=24, outline=(45, 55, 75), width=2)
    draw.rounded_rectangle([164, 124, WIDTH - 164, HEIGHT - 124], radius=22, outline=(30, 40, 60), width=1)

    # Pill badge
    badge_text = "HINDSIGHT AI HACKATHON 2026 • OFFICIAL SUBMISSION"
    f_badge = get_font(20, bold=True)
    draw.rounded_rectangle([720, 220, 1200, 265], radius=14, fill=(30, 41, 59), outline=(99, 102, 241), width=2)
    draw.text((745, 230), badge_text, font=f_badge, fill=(165, 180, 252))

    # Title
    f_title = get_font(84, bold=True)
    draw.text((WIDTH // 2, 400), "LEDGERMIND", font=f_title, fill=(248, 250, 252), anchor="mm")

    # Subtitle
    f_sub = get_font(36, bold=True)
    draw.text((WIDTH // 2, 500), "Policy-Aware Institutional Memory for Accounts Payable", font=f_sub, fill=(129, 140, 248), anchor="mm")

    # Divider bar
    draw.line([(WIDTH // 2 - 180, 560), (WIDTH // 2 + 180, 560)], fill=(99, 102, 241), width=4)

    # Core value proposition
    f_desc = get_font(28)
    draw.text(
        (WIDTH // 2, 630),
        "Transforming invoice exceptions from raw arithmetic discrepancies into consistent, policy-governed decisions.",
        font=f_desc,
        fill=(203, 213, 225),
        anchor="mm",
    )

    # Tech stack pills
    tech_tags = ["🧠 Hindsight Vector DB", "⚖️ Version-Governed Policy RAG", "⚡ Groq Inference", "🔒 SQLite Persistence"]
    tag_x_start = 380
    tag_spacing = 300
    f_tag = get_font(22, bold=True)
    for idx, tag in enumerate(tech_tags):
        tx = tag_x_start + idx * tag_spacing
        draw.rounded_rectangle([tx - 130, 740, tx + 150, 790], radius=12, fill=(20, 27, 45), outline=(55, 65, 85), width=1)
        draw.text((tx + 10, 765), tag, font=f_tag, fill=(226, 232, 240), anchor="mm")

    out_path = FRAMES_DIR / "title_card.png"
    img.save(out_path)
    print(f"Saved {out_path}")

def create_architecture_card():
    img = Image.new("RGB", (WIDTH, HEIGHT), color=(11, 15, 25))
    draw = ImageDraw.Draw(img)
    draw_gradient_background(draw, WIDTH, HEIGHT, (10, 15, 28), (15, 23, 42))

    # Outer frame
    draw.rounded_rectangle([120, 80, WIDTH - 120, HEIGHT - 80], radius=24, outline=(45, 55, 75), width=2)

    # Header
    f_badge = get_font(20, bold=True)
    draw.rounded_rectangle([750, 110, 1170, 150], radius=12, fill=(30, 41, 59), outline=(16, 185, 129), width=2)
    draw.text((WIDTH // 2, 130), "ARCHITECTURAL INNOVATION", font=f_badge, fill=(52, 211, 153), anchor="mm")

    f_title = get_font(52, bold=True)
    draw.text((WIDTH // 2, 195), "The Central Breakthrough: Policy vs. Precedent", font=f_title, fill=(248, 250, 252), anchor="mm")

    f_sub = get_font(24)
    draw.text((WIDTH // 2, 245), "LedgerMind never blindly repeats history. It evaluates remembered precedents against current governing procurement rules.", font=f_sub, fill=(148, 163, 184), anchor="mm")

    # 4 Architecture Pillars
    pillars = [
        ("1. Deterministic Matcher", "Performs strict 3-way reconciliation (PO, GRN, Invoice) across 6 discrepancy types with Indian GST precision.", (99, 102, 241)),
        ("2. Hindsight Vector DB", "Retains verified human reviews and recalls relevant multi-pass precedents with deduplicated observation facts.", (168, 85, 247)),
        ("3. Policy-RAG Engine", "Retrieves active corporate policy clauses and detects conflicts between past waivers and present constraints.", (236, 72, 153)),
        ("4. Human Accountability", "Authorized reviewers inspect explainable evidence, execute overrides, and teach institutional memory.", (16, 185, 129)),
    ]

    p_w = 380
    p_h = 420
    start_x = 170
    start_y = 310
    gap = 420

    f_phead = get_font(24, bold=True)
    f_pbody = get_font(20)

    for i, (title, desc, accent) in enumerate(pillars):
        px = start_x + i * gap
        draw.rounded_rectangle([px, start_y, px + p_w, start_y + p_h], radius=16, fill=(20, 28, 48), outline=accent, width=2)
        # Top banner in card
        draw.rounded_rectangle([px + 10, start_y + 10, px + p_w - 10, start_y + 70], radius=10, fill=(30, 41, 65))
        draw.text((px + p_w // 2, start_y + 40), title, font=f_phead, fill=(248, 250, 252), anchor="mm")

        # Multi-line description
        words = desc.split()
        lines = []
        cur = []
        for w in words:
            cur.append(w)
            if len(" ".join(cur)) > 26:
                lines.append(" ".join(cur))
                cur = []
        if cur:
            lines.append(" ".join(cur))

        for l_idx, line in enumerate(lines):
            draw.text((px + 24, start_y + 110 + l_idx * 34), line, font=f_pbody, fill=(203, 213, 225))

    # Footer note
    f_foot = get_font(22, bold=True)
    draw.text((WIDTH // 2, 880), "⭐ Result: Explainable, audit-proof accounts payable resolutions with zero circular confidence inflation.", font=f_foot, fill=(245, 158, 11), anchor="mm")

    out_path = FRAMES_DIR / "architecture_card.png"
    img.save(out_path)
    print(f"Saved {out_path}")

def create_closing_card():
    img = Image.new("RGB", (WIDTH, HEIGHT), color=(11, 15, 25))
    draw = ImageDraw.Draw(img)
    draw_gradient_background(draw, WIDTH, HEIGHT, (9, 13, 24), (17, 24, 39))

    draw.rounded_rectangle([160, 120, WIDTH - 160, HEIGHT - 120], radius=24, outline=(45, 55, 75), width=2)

    f_badge = get_font(20, bold=True)
    draw.rounded_rectangle([780, 210, 1140, 255], radius=12, fill=(30, 41, 59), outline=(99, 102, 241), width=2)
    draw.text((WIDTH // 2, 232), "SUMMARY & FUTURE ROADMAP", font=f_badge, fill=(165, 180, 252), anchor="mm")

    f_title = get_font(60, bold=True)
    draw.text((WIDTH // 2, 350), "LedgerMind", font=f_title, fill=(248, 250, 252), anchor="mm")

    f_quote = get_font(32)
    draw.text(
        (WIDTH // 2, 450),
        '"Helping finance teams move from detecting invoice exceptions to making consistent, policy-backed decisions."',
        font=f_quote,
        fill=(147, 197, 253),
        anchor="mm",
    )

    # 3 Summary columns
    items = [
        ("Working Prototype", "Full end-to-end user intake, 3-way matching, resolution workbench, and SQLite persistence."),
        ("Key Technical Lesson", "Decouple synchronous health checks from vector similarity queries; isolate supplier tag taxonomies."),
        ("Enterprise Roadmap", "Native ERP connectors (SAP, Oracle), automated OCR extraction, and multi-tenant enterprise RBAC."),
    ]

    col_w = 480
    col_gap = 520
    col_start_x = 200
    col_y = 570
    f_chead = get_font(24, bold=True)
    f_cbody = get_font(19)

    for i, (head, body) in enumerate(items):
        cx = col_start_x + i * col_gap
        draw.rounded_rectangle([cx, col_y, cx + col_w, col_y + 200], radius=14, fill=(20, 28, 48), outline=(50, 60, 80), width=1)
        draw.text((cx + col_w // 2, col_y + 40), head, font=f_chead, fill=(248, 250, 252), anchor="mm")

        words = body.split()
        lines = []
        cur = []
        for w in words:
            cur.append(w)
            if len(" ".join(cur)) > 30:
                lines.append(" ".join(cur))
                cur = []
        if cur:
            lines.append(" ".join(cur))

        for l_idx, line in enumerate(lines):
            draw.text((cx + 20, col_y + 80 + l_idx * 28), line, font=f_cbody, fill=(203, 213, 225))

    # Closing tag
    f_end = get_font(22, bold=True)
    draw.text((WIDTH // 2, 870), "Built with Hindsight Vector DB • November 2026", font=f_end, fill=(156, 163, 175), anchor="mm")

    out_path = FRAMES_DIR / "closing_card.png"
    img.save(out_path)
    print(f"Saved {out_path}")

if __name__ == "__main__":
    create_title_card()
    create_architecture_card()
    create_closing_card()

