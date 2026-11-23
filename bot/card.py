"""Imagen de cabecera AZ Pisos — plantilla A (Rojo marca), 1080x1350."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"
LOGO = ROOT / "assets" / "logo.png"

W, H, M = 1080, 1350, 80
RED_TL, RED_BR = (178, 51, 64), (90, 16, 27)
RED = (155, 28, 28)
WHITE = (255, 255, 255)
PINK = (255, 225, 228)
LABEL = (140, 90, 95)


def _font(weight, size):
    return ImageFont.truetype(str(FONTS / f"Barlow-{weight}.ttf"), size)


def _white_mark():
    src = Image.open(LOGO).convert("RGB")
    lum = np.asarray(src).astype(np.int32).min(axis=2)
    alpha = np.clip((lum - 120) * 255 / 110, 0, 255).astype(np.uint8)
    mark = Image.new("RGBA", src.size, (255, 255, 255, 0))
    mark.putalpha(Image.fromarray(alpha))
    return mark


def _background():
    y, x = np.mgrid[0:H, 0:W]
    t = ((x / W + y / H) / 2)[..., None]
    g = np.array(RED_TL) * (1 - t) + np.array(RED_BR) * t
    img = Image.fromarray(g.astype(np.uint8), "RGB").convert("RGBA")
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for k in range(-H, W + H, 46):
        d.line([(k, 0), (k + H, H)], fill=(255, 255, 255, 16), width=1)
    return Image.alpha_composite(img, ov)


def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=font) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _fit_headline(draw, text, max_w, max_h):
    for size in range(124, 60, -4):
        f = _font("ExtraBold", size)
        lines = _wrap(draw, text, f, max_w)
        lh = int(size * 1.08)
        widest = max(draw.textlength(l, font=f) for l in lines)
        if len(lines) * lh <= max_h and widest <= max_w:
            return f, lines, lh
    f = _font("ExtraBold", 60)
    return f, _wrap(draw, text, f, max_w)[:5], 65


def _fit_text(draw, text, weight, start, max_w):
    size = start
    while size > 20 and draw.textlength(text, font=_font(weight, size)) > max_w:
        size -= 2
    return _font(weight, size)


def _overlaps(boxes):
    names = list(boxes)
    bad = []
    for n, b in boxes.items():
        if b[0] < 0 or b[1] < 0 or b[2] > W or b[3] > H:
            bad.append(f"{n} fuera del lienzo")
    for i, a in enumerate(names):
        for c in names[i + 1:]:
            A, B = boxes[a], boxes[c]
            if A[0] < B[2] and B[0] < A[2] and A[1] < B[3] and B[1] < A[3]:
                bad.append(f"{a} solapa {c}")
    return bad


def render(city, headline, kpis, footer_left, footer_right, out_path):
    """kpis: lista de 3 tuplas (etiqueta, valor). Devuelve lista de problemas (vacía si OK)."""
    img = _background()
    img.alpha_composite(_white_mark().resize((150, 150), Image.LANCZOS), (M - 18, 62))
    d = ImageDraw.Draw(img)
    boxes = {"logo": (M - 18, 62, M + 132, 212)}

    def text(xy, s, f, fill, name, anchor="la"):
        d.text(xy, s, font=f, fill=fill, anchor=anchor)
        boxes[name] = d.textbbox(xy, s, font=f, anchor=anchor)

    text((M + 150, 98), "AZ PISOS", _font("ExtraBold", 54), WHITE, "brand")
    text((M + 152, 160), "Oportunidades inmobiliarias", _font("Medium", 28), PINK, "brandsub")

    pf, s = _font("Bold", 26), "OFF MARKET"
    pw = d.textlength(s, font=pf) + 48
    px = int(W - M - pw)
    d.rounded_rectangle((px, 110, W - M, 160), 25, fill=WHITE)
    d.text((px + 24, 135), s, font=pf, fill=RED, anchor="lm")
    boxes["pill"] = (px, 110, W - M, 160)

    # ciudad
    d.line([(M, 330), (M + 70, 330)], fill=WHITE, width=5)
    cf = _fit_text(d, city.upper(), "SemiBold", 34, W - 2 * M - 90)
    text((M + 90, 330), city.upper(), cf, PINK, "city", anchor="lm")

    # titular (zona 380..860)
    f, lines, lh = _fit_headline(d, headline, W - 2 * M, 860 - 380)
    y = 380
    for i, line in enumerate(lines):
        text((M - 4, y), line, f, WHITE, f"h{i}")
        y += lh

    # tarjetas KPI
    cy0, cy1, gap = 900, 1130, 24
    cw = (W - 2 * M - 2 * gap) // 3
    for i, (lab, val) in enumerate(kpis[:3]):
        x0 = M + i * (cw + gap)
        d.rounded_rectangle((x0, cy0, x0 + cw, cy1), 26, fill=WHITE)
        lf = _fit_text(d, lab.upper(), "SemiBold", 26, cw - 30)
        d.text((x0 + cw // 2, cy0 + 60), lab.upper(), font=lf, fill=LABEL, anchor="mm")
        vf = _fit_text(d, val, "ExtraBold", 66 if i == 2 else 54, cw - 30)
        d.text((x0 + cw // 2, cy0 + 140), val, font=vf, fill=RED, anchor="mm")
    boxes["cards"] = (M, cy0, W - M, cy1)

    # pie
    d.line([(M, 1200), (W - M, 1200)], fill=(255, 255, 255, 90), width=2)
    half = (W - 2 * M) // 2 - 20
    text((M, 1250), footer_left, _fit_text(d, footer_left, "Bold", 30, half), WHITE, "foot_l", anchor="lm")
    text((W - M, 1250), footer_right, _fit_text(d, footer_right, "Medium", 30, half), PINK, "foot_r", anchor="rm")

    problems = _overlaps(boxes)
    img.convert("RGB").save(out_path, quality=95)
    return problems
