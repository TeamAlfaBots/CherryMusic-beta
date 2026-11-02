# _thumbnails.py
# CHERRY-STYLE NOW PLAYING CARD
# - Song banner = full blurred background
# - Same banner is used inside the glass player card (frosted)
# - Left: album art tile | Right: info, progress, controls, volume bar

import math
import os
import aiohttp

from PIL import (
    Image,
    ImageChops,
    ImageDraw,
    ImageEnhance,
    ImageFilter,
    ImageFont,
    ImageOps
)

from opus import config

# ─────────────────────────────
# THEME
# ─────────────────────────────

ACCENT = (255, 77, 166)          # cherry pink
ACCENT_SOFT = (255, 150, 205)
WHITE = (255, 255, 255)
BG_DARK = (8, 4, 12)

BRAND = "Tulip"                  # "Tulip Now Playing"
WATERMARK = "TulipMusic  •  Powered by AlfaBots"

SIZE = (1280, 720)

FONT_DIR = "opus/helpers/"
CACHE_DIR = "cache"

_FONT_CACHE = {}


def _font(name, size):
    key = (name, size)
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = ImageFont.truetype(FONT_DIR + name, size)
    return _FONT_CACHE[key]


# ─────────────────────────────
# GENERIC HELPERS
# ─────────────────────────────

def _linear_gradient(size, c1, c2, vertical=True):
    w, h = size
    img = Image.new("RGBA", size)
    draw = ImageDraw.Draw(img)
    n = h if vertical else w
    for i in range(n):
        t = i / max(n - 1, 1)
        col = (
            int(c1[0] + (c2[0] - c1[0]) * t),
            int(c1[1] + (c2[1] - c1[1]) * t),
            int(c1[2] + (c2[2] - c1[2]) * t),
            255,
        )
        if vertical:
            draw.line((0, i, w, i), fill=col)
        else:
            draw.line((i, 0, i, h), fill=col)
    return img


def _text(base, xy, text, font, fill):
    """Alpha-correct text (draws on a small transparent layer, then pastes)."""
    l, t, r, b = font.getbbox(text)
    layer = Image.new("RGBA", (r + 8, b + 8), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((0, 0), text, font=font, fill=fill)
    base.paste(layer, (int(xy[0]), int(xy[1])), layer)


def _fit_text(draw, text, font, max_width):
    if draw.textlength(text, font=font) <= max_width:
        return text
    trimmed = text
    while draw.textlength(trimmed + "...", font=font) > max_width and len(trimmed) > 3:
        trimmed = trimmed[:-1]
    return trimmed.rstrip() + "..."


def _fit_font(draw, text, name, start, min_size, max_width):
    """Shrink the font first; ellipsis only if it still doesn't fit."""
    size = start
    while size > min_size:
        f = _font(name, size)
        if draw.textlength(text, font=f) <= max_width:
            return f, text
        size -= 2
    f = _font(name, min_size)
    return f, _fit_text(draw, text, f, max_width)


def _pill(base, x, y, w, h, fill, outline=None, radius=None):
    radius = radius if radius is not None else h // 2
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(
        (0, 0, w - 1, h - 1),
        radius=radius,
        fill=fill,
        outline=outline,
        width=1 if outline else 0,
    )
    base.paste(layer, (x, y), layer)


def _glow(base, cx, cy, radius, color, blur=28):
    pad = blur * 3
    size = radius * 2 + pad * 2
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse((pad, pad, pad + radius * 2, pad + radius * 2), fill=color)
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    base.paste(layer, (int(cx - radius - pad), int(cy - radius - pad)), layer)


# ─────────────────────────────
# BACKGROUND (banner → full blurred canvas)
# ─────────────────────────────

def _build_backdrop(song_img):
    bg = ImageOps.fit(song_img.convert("RGB"), SIZE, method=Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(38))
    bg = ImageEnhance.Brightness(bg).enhance(0.62)
    bg = ImageEnhance.Color(bg).enhance(1.25)
    bg = bg.convert("RGBA")

    overlay = Image.new("RGBA", SIZE, (*BG_DARK, 90))
    return Image.alpha_composite(bg, overlay)


# ─────────────────────────────
# GLASS CARD — same background shows through, frosted
# ─────────────────────────────

def _rr_mask(w, h, radius):
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    return m


def _draw_card_glow(base, x, y, w, h, radius):
    """Soft pink neon glow just outside the card edge."""
    pad = 60
    layer = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(
        (pad, pad, pad + w, pad + h), radius=radius, outline=(*ACCENT, 150), width=5
    )
    layer = layer.filter(ImageFilter.GaussianBlur(16))
    base.paste(layer, (x - pad, y - pad), layer)


def _draw_glass_card(base, x, y, w, h, radius=44, blur=14):
    # crop from the SAME blurred background → card carries the banner inside it
    crop = base.crop((x, y, x + w, y + h)).filter(ImageFilter.GaussianBlur(blur))
    crop = ImageEnhance.Brightness(crop).enhance(1.15)

    crop = Image.alpha_composite(crop, Image.new("RGBA", (w, h), (16, 10, 24, 105)))
    crop = Image.alpha_composite(crop, Image.new("RGBA", (w, h), (255, 255, 255, 10)))

    mask = _rr_mask(w, h, radius)
    crop.putalpha(mask)
    base.paste(crop, (x, y), crop)

    # top sheen
    sh_h = h // 3
    grad = ImageOps.invert(Image.linear_gradient("L").resize((w, sh_h)))
    grad = grad.point(lambda v: v * 30 // 255)
    full = Image.new("L", (w, h), 0)
    full.paste(grad, (0, 0))
    full = ImageChops.multiply(full, mask)
    sheen = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    sheen.putalpha(full)
    base.paste(sheen, (x, y), sheen)

    # glass rim
    rim = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(rim).rounded_rectangle(
        (0, 0, w - 1, h - 1), radius=radius, outline=(255, 255, 255, 95), width=2
    )
    base.paste(rim, (x, y), rim)


# ─────────────────────────────
# ICONS (drawn 4x then downsampled → smooth edges)
# All icon fns take (draw, S) and use fractions of S.
# ─────────────────────────────

def _icon(base, cx, cy, box, fn, ss=4):
    S = box * ss
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    fn(ImageDraw.Draw(layer), S)
    layer = layer.resize((box, box), Image.LANCZOS)
    base.paste(layer, (int(cx - box // 2), int(cy - box // 2)), layer)


def ic_bars(color):
    def fn(d, S):
        hs = [0.45, 0.95, 0.65, 0.8]
        bw, gap = 0.15 * S, 0.09 * S
        x = 0.06 * S
        for hh in hs:
            top, bot = (0.5 - hh / 2) * S, (0.5 + hh / 2) * S
            d.rounded_rectangle((x, top, x + bw, bot), radius=bw / 2, fill=color)
            x += bw + gap
    return fn


def ic_shuffle(color):
    def fn(d, S):
        w = int(S * 0.08)
        d.line([(.08 * S, .3 * S), (.38 * S, .3 * S), (.62 * S, .7 * S), (.78 * S, .7 * S)],
               fill=color, width=w, joint="curve")
        d.line([(.08 * S, .7 * S), (.38 * S, .7 * S), (.62 * S, .3 * S), (.78 * S, .3 * S)],
               fill=color, width=w, joint="curve")
        for yy in (.3, .7):
            d.polygon([(.74 * S, (yy - .14) * S), (.74 * S, (yy + .14) * S), (.95 * S, yy * S)], fill=color)
    return fn


def ic_repeat(color):
    def fn(d, S):
        w = int(S * 0.08)
        d.line([(.15 * S, .55 * S), (.15 * S, .32 * S), (.76 * S, .32 * S)],
               fill=color, width=w, joint="curve")
        d.polygon([(.72 * S, .16 * S), (.72 * S, .48 * S), (.94 * S, .32 * S)], fill=color)
        d.line([(.85 * S, .45 * S), (.85 * S, .68 * S), (.24 * S, .68 * S)],
               fill=color, width=w, joint="curve")
        d.polygon([(.28 * S, .52 * S), (.28 * S, .84 * S), (.06 * S, .68 * S)], fill=color)
    return fn


def ic_prev(color):
    def fn(d, S):
        d.rounded_rectangle((.18 * S, .2 * S, .30 * S, .8 * S), radius=int(.02 * S), fill=color)
        d.polygon([(.84 * S, .2 * S), (.84 * S, .8 * S), (.36 * S, .5 * S)], fill=color)
    return fn


def ic_next(color):
    def fn(d, S):
        d.rounded_rectangle((.70 * S, .2 * S, .82 * S, .8 * S), radius=int(.02 * S), fill=color)
        d.polygon([(.16 * S, .2 * S), (.16 * S, .8 * S), (.64 * S, .5 * S)], fill=color)
    return fn


def ic_pause(color):
    def fn(d, S):
        d.rounded_rectangle((.26 * S, .2 * S, .43 * S, .8 * S), radius=int(.04 * S), fill=color)
        d.rounded_rectangle((.57 * S, .2 * S, .74 * S, .8 * S), radius=int(.04 * S), fill=color)
    return fn


def ic_heart(color):
    def fn(d, S):
        pts = []
        for i in range(120):
            t = i / 120 * 2 * math.pi
            x = 16 * math.sin(t) ** 3
            y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
            pts.append((0.5 * S + x * S / 36, 0.5 * S - (y + 2.5) * S / 36))
        d.polygon(pts, fill=color)
    return fn


def ic_dots(color):
    def fn(d, S):
        r = S * 0.07
        for cx in (.2, .5, .8):
            d.ellipse((cx * S - r, .5 * S - r, cx * S + r, .5 * S + r), fill=color)
    return fn


def ic_verified(color):
    def fn(d, S):
        d.ellipse((0, 0, S - 1, S - 1), fill=color)
        d.line([(.27 * S, .52 * S), (.44 * S, .68 * S), (.74 * S, .35 * S)],
               fill=(255, 255, 255, 255), width=int(S * 0.12), joint="curve")
    return fn


def ic_volume(color):
    def fn(d, S):
        d.polygon([(.08 * S, .38 * S), (.26 * S, .38 * S), (.48 * S, .18 * S),
                   (.48 * S, .82 * S), (.26 * S, .62 * S), (.08 * S, .62 * S)], fill=color)
        w = int(S * 0.07)
        d.arc((.34 * S, .32 * S, .70 * S, .68 * S), start=-50, end=50, fill=color, width=w)
        d.arc((.28 * S, .18 * S, .84 * S, .82 * S), start=-50, end=50, fill=color, width=w)
    return fn


def ic_sliders(color):
    def fn(d, S):
        w = int(S * 0.07)
        r = S * 0.12
        for yy, kx in ((.3, .66), (.7, .34)):
            d.line([(.08 * S, yy * S), (.92 * S, yy * S)], fill=color, width=w)
            d.ellipse((kx * S - r, yy * S - r, kx * S + r, yy * S + r),
                      fill=(0, 0, 0, 0), outline=color, width=w)
    return fn


def ic_device(color):
    def fn(d, S):
        w = int(S * 0.07)
        d.rounded_rectangle((.2 * S, .08 * S, .8 * S, .92 * S), radius=int(.1 * S), outline=color, width=w)
        r1 = S * 0.05
        d.ellipse((.5 * S - r1, .27 * S - r1, .5 * S + r1, .27 * S + r1), fill=color)
        r2 = S * 0.14
        d.ellipse((.5 * S - r2, .62 * S - r2, .5 * S + r2, .62 * S + r2), outline=color, width=w)
    return fn


def ic_fullscreen(color):
    def fn(d, S):
        w = int(S * 0.07)
        a, b = .12, .88
        for (cx, cy, dx, dy) in ((a, a, 1, 1), (b, a, -1, 1), (a, b, 1, -1), (b, b, -1, -1)):
            d.line([(cx * S, (cy + dy * .24) * S), (cx * S, cy * S), ((cx + dx * .24) * S, cy * S)],
                   fill=color, width=w, joint="curve")
            d.line([(cx * S, cy * S), ((cx + dx * .2) * S, (cy + dy * .2) * S)], fill=color, width=w)
    return fn


def ic_dot(color):
    def fn(d, S):
        d.ellipse((0, 0, S - 1, S - 1), fill=color)
    return fn


# ─────────────────────────────
# PROGRESS
# ─────────────────────────────

def _time_to_seconds(t):
    try:
        parts = [int(p) for p in str(t).split(":")]
        while len(parts) < 3:
            parts.insert(0, 0)
        h, m, s = parts[-3:]
        return h * 3600 + m * 60 + s
    except Exception:
        return 0


def _draw_progress(base, x, y, width, cur, end, font):
    H = 6
    track = Image.new("RGBA", (width, H), (0, 0, 0, 0))
    ImageDraw.Draw(track).rounded_rectangle((0, 0, width - 1, H - 1), radius=3, fill=(255, 255, 255, 70))
    base.paste(track, (x, y), track)

    cur_s = _time_to_seconds(cur)
    end_s = max(_time_to_seconds(end), 1)
    ratio = min(max(cur_s / end_s, 0.02), 1.0)
    fw = max(H, int(width * ratio))

    fill = _linear_gradient((fw, H), ACCENT_SOFT, ACCENT, vertical=False)
    mask = Image.new("L", (fw, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, fw - 1, H - 1), radius=3, fill=255)
    fill.putalpha(mask)

    # glow under the filled part
    gl = Image.new("RGBA", (fw + 40, H + 40), (0, 0, 0, 0))
    ImageDraw.Draw(gl).rounded_rectangle((20, 20, 20 + fw, 20 + H), radius=3, fill=(*ACCENT, 170))
    gl = gl.filter(ImageFilter.GaussianBlur(6))
    base.paste(gl, (x - 20, y - 20), gl)
    base.paste(fill, (x, y), fill)

    # knob
    kx, ky = x + fw, y + H // 2
    _glow(base, kx, ky, 8, (*ACCENT, 190), blur=8)
    _icon(base, kx, ky, 22, ic_dot((255, 255, 255, 255)))

    # times (below bar)
    _text(base, (x, y + 18), cur, font, (255, 255, 255, 210))
    d = ImageDraw.Draw(base)
    rw = int(d.textlength(end, font=font))
    _text(base, (x + width - rw, y + 18), end, font, (255, 255, 255, 210))


# ─────────────────────────────
# CONTROLS ROW
# ─────────────────────────────

def _draw_controls(base, x, cy, width):
    FG = (255, 255, 255, 255)
    PLAY = 92

    cx = lambda f: int(x + width * f)

    # shuffle / repeat (accent) + dots
    _icon(base, cx(0.05), cy, 46, ic_shuffle((*ACCENT, 255)))
    _icon(base, cx(0.05), cy + 40, 8, ic_dot((*ACCENT, 255)))
    _icon(base, cx(0.95), cy, 46, ic_repeat((*ACCENT, 255)))
    _icon(base, cx(0.95), cy + 40, 8, ic_dot((*ACCENT, 255)))

    # prev / next
    _icon(base, cx(0.27), cy, 48, ic_prev(FG))
    _icon(base, cx(0.73), cy, 48, ic_next(FG))

    # big glowing pause button
    pcx = cx(0.5)
    _glow(base, pcx, cy, PLAY // 2, (*ACCENT, 170), blur=26)
    _icon(base, pcx, cy, PLAY, ic_dot((255, 238, 246, 255)))
    _icon(base, pcx, cy, 44, ic_pause((22, 10, 20, 255)))


# ─────────────────────────────
# BOTTOM VOLUME BAR
# ─────────────────────────────

def _draw_volume_bar(base, x, y, w, h=64):
    _pill(base, x, y, w, h, (255, 255, 255, 22), (255, 255, 255, 60), h // 2)

    cy = y + h // 2
    _icon(base, x + 38, cy, 34, ic_volume((255, 255, 255, 235)))

    sx, ex = x + 74, x + w - 190
    sw = ex - sx
    track = Image.new("RGBA", (sw, 6), (0, 0, 0, 0))
    ImageDraw.Draw(track).rounded_rectangle((0, 0, sw - 1, 5), radius=3, fill=(255, 255, 255, 60))
    base.paste(track, (sx, cy - 3), track)

    fw = int(sw * 0.55)
    fill = _linear_gradient((fw, 6), ACCENT_SOFT, ACCENT, vertical=False)
    m = Image.new("L", (fw, 6), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, fw - 1, 5), radius=3, fill=255)
    fill.putalpha(m)
    base.paste(fill, (sx, cy - 3), fill)
    _icon(base, sx + fw, cy, 24, ic_dot((255, 255, 255, 255)))

    _icon(base, x + w - 138, cy, 32, ic_sliders((255, 255, 255, 235)))
    _icon(base, x + w - 86, cy, 32, ic_device((255, 255, 255, 235)))
    _icon(base, x + w - 36, cy, 32, ic_fullscreen((255, 255, 255, 235)))


# ─────────────────────────────
# MAIN CLASS
# ─────────────────────────────

class Thumbnail:

    def __init__(self):
        self.session = None
        os.makedirs(CACHE_DIR, exist_ok=True)

        self.f_label = _font("Raleway-Bold.ttf", 28)
        self.f_artist = _font("Inter-Light.ttf", 26)
        self.f_time = _font("Inter-Light.ttf", 20)
        self.f_power = _font("Inter-Light.ttf", 16)

    async def start(self):
        self.session = aiohttp.ClientSession()

    async def close(self):
        if self.session:
            await self.session.close()

    async def save_thumb(self, path, url):
        if not self.session:
            self.session = aiohttp.ClientSession()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        async with self.session.get(url) as resp:
            with open(path, "wb") as f:
                f.write(await resp.read())
        return path

    async def generate(self, song):
        try:
            W, H = SIZE
            temp = f"{CACHE_DIR}/temp_{song.id}.jpg"
            output = f"{CACHE_DIR}/{song.id}.png"

            await self.save_thumb(temp, song.thumbnail)
            raw = Image.open(temp).convert("RGBA")

            # 1) Banner → full-bleed blurred background
            base = _build_backdrop(raw)
            draw = ImageDraw.Draw(base)

            # 2) Glass card (background shows through inside it)
            CARD_W, CARD_H = 1160, 540
            CX = (W - CARD_W) // 2
            CY = (H - CARD_H) // 2 - 20
            R = 44

            _draw_card_glow(base, CX, CY, CARD_W, CARD_H, R)
            _draw_glass_card(base, CX, CY, CARD_W, CARD_H, radius=R)

            # 3) Album art tile (left, full card height)
            AS = CARD_H
            art = ImageOps.fit(raw.convert("RGB"), (AS, AS), method=Image.LANCZOS).convert("RGBA")
            art.putalpha(_rr_mask(AS, AS, R))
            base.paste(art, (CX, CY), art)

            rim = Image.new("RGBA", (AS, AS), (0, 0, 0, 0))
            ImageDraw.Draw(rim).rounded_rectangle(
                (0, 0, AS - 1, AS - 1), radius=R, outline=(255, 255, 255, 110), width=2
            )
            base.paste(rim, (CX, CY), rim)

            # 4) Right side layout
            RX = CX + AS + 48
            RR = CX + CARD_W - 48
            RW = RR - RX

            # Row 1: "Tulip Now Playing" + heart / more buttons
            row_cy = CY + 57
            _icon(base, RX + 16, row_cy, 32, ic_bars((*ACCENT, 255)))
            _text(base, (RX + 42, row_cy - 19), BRAND, self.f_label, (*ACCENT, 255))
            bw = int(draw.textlength(BRAND + " ", font=self.f_label))
            _text(base, (RX + 42 + bw, row_cy - 19), "Now Playing", self.f_label, (255, 255, 255, 245))

            B = 46
            more_x = RR - B
            heart_x = more_x - 14 - B
            _pill(base, heart_x, row_cy - B // 2, B, B, (*ACCENT, 45), (*ACCENT, 200), B // 2)
            _icon(base, heart_x + B // 2, row_cy, 26, ic_heart((*ACCENT, 255)))
            _pill(base, more_x, row_cy - B // 2, B, B, (255, 255, 255, 22), (255, 255, 255, 80), B // 2)
            _icon(base, more_x + B // 2, row_cy, 26, ic_dots((255, 255, 255, 240)))

            # Row 2: Title (big, auto-shrinks to fit)
            f_title, title = _fit_font(draw, song.title.strip(), "Raleway-Bold.ttf", 56, 34, RW)
            _text(base, (RX, CY + 100), title, f_title, (255, 255, 255, 255))

            # Row 3: Artist + verified tick
            ty = CY + 100 + f_title.size + 14
            channel = _fit_text(draw, song.channel_name, self.f_artist, RW - 44)
            _text(base, (RX, ty), channel, self.f_artist, (255, 255, 255, 170))
            cw = int(draw.textlength(channel, font=self.f_artist))
            _icon(base, RX + cw + 24, ty + 17, 26, ic_verified((*ACCENT, 255)))

            # Row 4: Progress bar + times
            prog_y = CY + 262
            _draw_progress(base, RX, prog_y, RW, "0:01", song.duration, self.f_time)

            # Row 5: Controls
            _draw_controls(base, RX, CY + 362, RW)

            # Row 6: Volume bar
            _draw_volume_bar(base, RX, CY + CARD_H - 34 - 64, RW, 64)

            # 5) Watermark under the card
            w2 = int(draw.textlength(WATERMARK, font=self.f_power))
            _text(base, ((W - w2) // 2, CY + CARD_H + 34), WATERMARK, self.f_power, (255, 255, 255, 150))

            base.convert("RGB").save(output)

            try:
                os.remove(temp)
            except OSError:
                pass

            return output

        except Exception as e:
            print(f"[Thumbnail] generation failed: {e}")
            return config.DEFAULT_THUMB
