"""Render a ~48s demo video of scraper.py from the real run log and real Excel output."""
import math
import subprocess
import sys
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

PROJ = Path(__file__).resolve().parent.parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJ / "video" / "scraper_demo.mp4"
FPS, S = 30, 1.5                      # layout in 1280x720 units, rendered at 1920x1080
W, H = int(1280 * S), int(720 * S)

INTER = "/usr/share/fonts/opentype/inter/Inter-{}.otf"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono{}.ttf"
_fc = {}
def font(kind, size, weight="Regular"):
    key = (kind, size, weight)
    if key not in _fc:
        path = INTER.format(weight) if kind == "sans" else MONO.format("" if weight == "Regular" else "-Bold")
        _fc[key] = ImageFont.truetype(path, int(size * S))
    return _fc[key]

def s(*v): return [int(round(x * S)) for x in v]

BG = (236, 240, 244)
TERM_BG, TERM_BAR = (30, 32, 39), (46, 49, 58)
GREEN, HEAD_GREEN = (80, 230, 120), (31, 111, 67)
TXT, MUTED, GRID = (34, 38, 46), (95, 102, 112), (218, 222, 228)
WIN = (120, 84, 1040, 580)            # x, y, w, h of the app window

log_lines = (PROJ / "output" / "run_log.txt").read_text().splitlines()
done_line = next(l for l in log_lines if l.startswith("Done:"))
done_line = done_line.replace(str(PROJ) + "/", "")  # keep the path short on screen
page_lines = [l for l in log_lines if l.strip().startswith("page ")]
sheets = pd.read_excel(PROJ / "output" / "books_data.xlsx", sheet_name=None)
books, rating = sheets["Books"], sheets["By Rating"]

# ---------------- timeline (seconds) ----------------
CMD1, CMD2 = "python scraper.py", "xdg-open output/books_data.xlsx"
T_TYPE1, CH = 0.9, 0.075
T_SCRAPE = T_TYPE1 + len(CMD1) * CH + 0.35
T_PAGE0, PAGE_DT = T_SCRAPE + 0.55, 0.42
T_DONE = T_PAGE0 + len(page_lines) * PAGE_DT + 0.3
T_TYPE2 = T_DONE + 1.8
T_SHEET = T_TYPE2 + len(CMD2) * CH + 0.4
T_SCROLL0, T_SCROLL1 = T_SHEET + 2.4, T_SHEET + 8.6
T_CURSOR0 = T_SCROLL1 + 1.6
T_CLICK = T_CURSOR0 + 1.2
T_END = T_CLICK + 4.2
TOTAL = T_END + 4.0

def ease(t): t = max(0.0, min(1.0, t)); return t * t * (3 - 2 * t)

def caption(d, text, step):
    f = font("sans", 15, "SemiBold")
    x, y = s(120, 36)
    tw = d.textlength(text, font=f)
    d.rounded_rectangle([x, y, x + tw + s(52)[0], y + s(30)[0]], radius=s(15)[0], fill=(255, 255, 255))
    d.ellipse([x + s(7)[0], y + s(6)[0], x + s(25)[0], y + s(24)[0]], fill=HEAD_GREEN)
    d.text((x + s(16)[0], y + s(15)[0]), str(step), font=font("sans", 11, "Bold"), fill="white", anchor="mm")
    d.text((x + s(34)[0], y + s(15)[0]), text, font=f, fill=TXT, anchor="lm")

def badge(d, text):
    f = font("sans", 13, "SemiBold")
    tw = d.textlength(text, font=f)
    x1, y = s(1160)[0], s(38)[0]
    d.rounded_rectangle([x1 - tw - s(24)[0], y, x1, y + s(26)[0]], radius=s(13)[0], fill=(255, 236, 200))
    d.text((x1 - s(12)[0], y + s(13)[0]), text, font=f, fill=(140, 84, 0), anchor="rm")

def shadow_window(d, title_h):
    x, y, w, h = WIN
    d.rounded_rectangle(s(x, y + 5, x + w, y + h + 5), radius=s(12)[0], fill=(205, 211, 219))

# ---------------- terminal ----------------
def terminal(t):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    x, y, w, h = WIN
    shadow_window(d, 34)
    d.rounded_rectangle(s(x, y, x + w, y + h), radius=s(12)[0], fill=TERM_BG)
    d.rounded_rectangle(s(x, y, x + w, y + 34), radius=s(12)[0], fill=TERM_BAR)
    d.rectangle(s(x, y + 22, x + w, y + 34), fill=TERM_BAR)
    for i, c in enumerate([(255, 95, 87), (254, 188, 46), (40, 200, 64)]):
        cx = x + 20 + i * 20
        d.ellipse(s(cx - 6, y + 11, cx + 6, y + 23), fill=c)
    d.text(s(x + w / 2, y + 17), "web-scraper — bash", font=font("sans", 13), fill=(170, 175, 185), anchor="mm")

    mono, bold = font("mono", 15), font("mono", 15, "Bold")
    lines = []  # (text, style)
    typed1 = CMD1[:max(0, min(len(CMD1), int((t - T_TYPE1) / CH)))] if t >= T_TYPE1 else ""
    lines.append(("$ " + typed1, "cmd"))
    if t >= T_SCRAPE:
        lines.append(("Scraping books.toscrape.com ...", "out"))
        n = 0 if t < T_PAGE0 else min(len(page_lines), int((t - T_PAGE0) / PAGE_DT) + 1)
        lines += [(l, "out") for l in page_lines[:n]]
    if t >= T_DONE:
        lines.append((done_line, "done"))
        typed2 = CMD2[:max(0, min(len(CMD2), int((t - T_TYPE2) / CH)))] if t >= T_TYPE2 else ""
        lines.append(("$ " + typed2, "cmd"))
    running = T_SCRAPE <= t < T_DONE

    lh, max_lines = 22, 22
    visible = lines[-max_lines:]
    ty = y + 34 + 18
    for text, style in visible:
        if style == "cmd":
            d.text(s(x + 22, ty), "$", font=bold, fill=GREEN)
            d.text(s(x + 22 + 18, ty), text[2:], font=bold, fill=(240, 240, 240))
            end_x = x + 22 + 18 + d.textlength(text[2:], font=bold) / S
        else:
            d.text(s(x + 22, ty), text, font=bold if style == "done" else mono,
                   fill=GREEN if style == "done" else (210, 212, 218))
        ty += lh
    # blinking cursor on the active prompt line (hidden while the scraper runs)
    if not running and visible[-1][1] == "cmd" and (int(t * 2.5) % 2 == 0 or T_TYPE1 <= t < T_TYPE1 + len(CMD1) * CH or T_TYPE2 <= t < T_TYPE2 + len(CMD2) * CH):
        cy = y + 34 + 18 + (len(visible) - 1) * lh
        d.rectangle(s(end_x + 2, cy + 1, end_x + 11, cy + 19), fill=(220, 220, 220))

    if t < T_SCRAPE:
        caption(d, "Run the scraper", 1)
    elif t < T_TYPE2:
        caption(d, "It follows all 50 pages automatically", 2)
        if running:
            badge(d, "sped up ~10×  (real run: 200 s)")
    else:
        caption(d, "Open the Excel file it produced", 3)
    return img

# ---------------- spreadsheet ----------------
BOOK_COLS = [("Title", 410, "l"), ("Price (GBP)", 110, "r"), ("Rating (1-5)", 110, "r"),
             ("In Stock", 90, "c"), ("URL", None, "l")]
RATE_COLS = [("Rating (1-5)", 170, "r"), ("Books", 130, "r"), ("Avg Price (GBP)", 190, "r"), ("", None, "l")]
ROW_H, RN_W, TOP_H, COLHDR_H, TAB_H = 25, 44, 34, 22, 34

def fit(d, text, f, maxw):
    if d.textlength(text, font=f) <= maxw: return text
    while text and d.textlength(text + "…", font=f) > maxw: text = text[:-1]
    return text + "…"

def fmt(col, v):
    if "GBP" in col: return f"£{v:,.2f}"
    if col == "In Stock": return "TRUE" if v else "FALSE"
    return str(v)

def sheet(active, scroll_px, cursor=None, pressed=False):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    x, y, w, h = WIN
    shadow_window(d, TOP_H)
    d.rounded_rectangle(s(x, y, x + w, y + h), radius=s(12)[0], fill="white")
    d.rounded_rectangle(s(x, y, x + w, y + TOP_H), radius=s(12)[0], fill=(247, 248, 250))
    d.rectangle(s(x, y + 20, x + w, y + TOP_H), fill=(247, 248, 250))
    d.rounded_rectangle(s(x + 14, y + 9, x + 30, y + 25), radius=s(3)[0], fill=HEAD_GREEN)
    d.text(s(x + 22, y + 17), "X", font=font("sans", 10, "Bold"), fill="white", anchor="mm")
    d.text(s(x + 40, y + 17), "books_data.xlsx", font=font("sans", 13, "SemiBold"), fill=TXT, anchor="lm")

    df, cols = (books, BOOK_COLS) if active == "Books" else (rating, RATE_COLS)
    xs = [x + RN_W]
    for _, cw, _ in cols:
        xs.append(xs[-1] + cw if cw else x + w)
    grid_top = y + TOP_H
    body_top = grid_top + COLHDR_H + ROW_H        # header row 1 is frozen
    body_bot = y + h - TAB_H
    f, fb, fs = font("sans", 13), font("sans", 13, "SemiBold"), font("sans", 11)

    # body rows (clipped by drawing onto a separate layer)
    layer = Image.new("RGB", s(w, body_bot - body_top), "white")
    ld = ImageDraw.Draw(layer)
    first = int(scroll_px // ROW_H)
    off = scroll_px - first * ROW_H
    n_rows = max(len(df), 40)
    for i in range(first, min(n_rows, first + (body_bot - body_top) // ROW_H + 2)):
        ry = (i - first) * ROW_H - off
        ld.rectangle(s(0, ry, RN_W, ry + ROW_H), fill=(247, 248, 250))
        ld.text(s(RN_W / 2, ry + ROW_H / 2), str(i + 2), font=fs, fill=MUTED, anchor="mm")
        ld.line(s(0, ry + ROW_H, w, ry + ROW_H), fill=GRID, width=1)
        if i < len(df):
            for c, (name, _, al) in enumerate(cols):
                if not name: continue
                cx0, cx1 = xs[c] - x, xs[c + 1] - x
                txt = fit(ld, fmt(name, df[name].iloc[i]), f, (cx1 - cx0 - 16) * S)
                ax = {"l": cx0 + 8, "r": cx1 - 8, "c": (cx0 + cx1) / 2}[al]
                ld.text(s(ax, ry + ROW_H / 2), txt, font=f, fill=TXT, anchor={"l": "lm", "r": "rm", "c": "mm"}[al])
    for c in range(len(cols)):
        ld.line(s(xs[c] - x, 0, xs[c] - x, body_bot - body_top), fill=GRID, width=1)
    img.paste(layer, s(x, body_top))

    # column letters + frozen header row
    d.rectangle(s(x, grid_top, x + w, grid_top + COLHDR_H), fill=(247, 248, 250))
    d.rectangle(s(x, grid_top + COLHDR_H, x + RN_W, body_top), fill=(247, 248, 250))
    d.text(s(x + RN_W / 2, grid_top + COLHDR_H + ROW_H / 2), "1", font=fs, fill=MUTED, anchor="mm")
    for c, (name, _, _) in enumerate(cols):
        d.text(s((xs[c] + xs[c + 1]) / 2, grid_top + COLHDR_H / 2), "ABCDE"[c], font=fs, fill=MUTED, anchor="mm")
        if name:
            d.rectangle(s(xs[c], grid_top + COLHDR_H, xs[c + 1], body_top), fill=HEAD_GREEN)
            d.text(s((xs[c] + xs[c + 1]) / 2, grid_top + COLHDR_H + ROW_H / 2), name, font=fb, fill="white", anchor="mm")
        d.line(s(xs[c], grid_top, xs[c], body_top), fill=GRID, width=1)
    d.line(s(x, grid_top + COLHDR_H, x + w, grid_top + COLHDR_H), fill=GRID, width=1)
    d.line(s(x, body_top, x + w, body_top), fill=(170, 176, 186), width=s(2)[0])

    # sheet tabs
    d.rectangle(s(x, body_bot, x + w, y + h - 12), fill=(247, 248, 250))
    d.rounded_rectangle(s(x, body_bot, x + w, y + h), radius=s(12)[0], fill=(247, 248, 250))
    d.line(s(x, body_bot, x + w, body_bot), fill=GRID, width=1)
    for name, tx in (("Books", x + 50), ("By Rating", x + 145)):
        on = name == active
        d.text(s(tx, body_bot + TAB_H / 2), name, font=font("sans", 13, "SemiBold" if on else "Regular"),
               fill=HEAD_GREEN if on else MUTED, anchor="mm")
        if on:
            tw = d.textlength(name, font=font("sans", 13, "SemiBold")) / S
            d.rectangle(s(tx - tw / 2 - 12, body_bot + TAB_H - 5, tx + tw / 2 + 12, body_bot + TAB_H - 3), fill=HEAD_GREEN)

    # scrollbar (Books sheet only)
    if active == "Books":
        track = body_bot - body_top - 8
        total = len(df) * ROW_H
        view = body_bot - body_top
        th = max(30, track * view / total)
        ty = body_top + 4 + (track - th) * (scroll_px / max(1, total - view))
        d.rounded_rectangle(s(x + w - 9, ty, x + w - 4, ty + th), radius=s(3)[0], fill=(180, 186, 196))

    if cursor:
        cx, cy = cursor
        if pressed:
            d.ellipse(s(cx - 14, cy - 14, cx + 14, cy + 14), outline=HEAD_GREEN, width=s(2)[0])
        pts = [(0, 0), (0, 17), (4.5, 13), (7.5, 20), (10, 19), (7, 12.5), (12.5, 12.5)]
        d.polygon([tuple(s(cx + px, cy + py)) for px, py in pts], fill="black", outline="white")

    if active == "Books":
        caption(d, "A clean, formatted Excel file — 1,000 rows", 4)
    else:
        caption(d, "Plus a summary sheet", 5)
    return img

def end_card():
    img = Image.new("RGB", (W, H), (20, 54, 36))
    d = ImageDraw.Draw(img)
    d.text(s(640, 285), "Custom Python Web Scraping", font=font("sans", 46, "Bold"), fill="white", anchor="mm")
    d.text(s(640, 350), "Any website  →  clean Excel / CSV", font=font("sans", 26, "Medium"), fill=(170, 230, 190), anchor="mm")
    d.text(s(640, 420), "Pagination  ·  Automatic retries  ·  Polite rate limiting  ·  Formatted output",
           font=font("sans", 17), fill=(205, 220, 210), anchor="mm")
    return img

# ---------------- render ----------------
books_view = (WIN[3] - TOP_H - COLHDR_H - ROW_H - TAB_H)
max_scroll = len(books) * ROW_H - books_view
tab_xy = (WIN[0] + 145, WIN[1] + WIN[3] - TAB_H / 2 + 2)

def frame(t):
    if t < T_SHEET:
        return terminal(t)
    if t < T_CLICK:
        scroll = max_scroll * ease((t - T_SCROLL0) / (T_SCROLL1 - T_SCROLL0))
        cur = None
        if t >= T_CURSOR0:
            p = ease((t - T_CURSOR0) / (T_CLICK - T_CURSOR0 - 0.15))
            cur = (760 + (tab_xy[0] - 760) * p, 420 + (tab_xy[1] - 420) * p)
        img = sheet("Books", scroll, cur, pressed=t > T_CLICK - 0.15)
        if t < T_SHEET + 0.6:  # open transition
            return Image.blend(terminal(t), img, ease((t - T_SHEET) / 0.6))
        return img
    if t < T_END:
        img = sheet("By Rating", 0, tab_xy if t < T_CLICK + 1.2 else None, pressed=t < T_CLICK + 0.2)
        return img
    a = ease((t - T_END) / 0.6)
    return Image.blend(sheet("By Rating", 0), end_card(), a) if a < 1 else end_card()

OUT.parent.mkdir(parents=True, exist_ok=True)
ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                       "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "slow",
                       "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(OUT)],
                      stdin=subprocess.PIPE)
n = int(TOTAL * FPS)
for i in range(n):
    ff.stdin.write(frame(i / FPS).tobytes())
ff.stdin.close()
ff.wait()
print(f"{OUT}  {TOTAL:.1f}s  {n} frames")
