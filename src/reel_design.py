"""Design tokens and static artwork for the comparison reel.

The reel has to speak the same visual language as the application, so the values below are the
ones in design-system.css, ltx-studio.css and h3-studio.css: the same background, the same accent
ramp per engine, the same condensed display face, the same rounded surfaces and muted microcopy.

ffmpeg cannot draw a radial falloff, a rounded corner or a chip, so those are generated once as
images and composited. Everything here is deterministic: the same tokens produce byte-identical
artwork, so a rendered reel can be reasoned about from the constants.
"""
from __future__ import annotations

import math
import subprocess
from pathlib import Path

# --- tokens, copied from the application stylesheets ---------------------------------------
BASE = {
    "bg": (0x10, 0x10, 0x14),
    "surface": (0x18, 0x18, 0x1F),
    "stage": (0x08, 0x08, 0x0B),
    "text": (0xF7, 0xF5, 0xF1),
    "subtle": (0x73, 0x71, 0x7D),
    "line_alpha": 0.10,
    "text_alpha": 1.0,
    "subtle_alpha": 1.0,
}
ENGINES = {
    "ltx25-ripple": {
        "accent": (0x22, 0xD3, 0xEE),
        "accent_soft": 0.13,     # --accent-soft, the ambient glow
        "accent_glow": 0.25,     # --accent-glow, the tighter one
        "stack": "FLUX 2 Klein + LTX 2.5 + Ripple",
    },
    "minimax-h3": {
        "accent": (0xFF, 0x4F, 0x2E),
        "accent_soft": 0.13,
        "accent_glow": 0.25,
        "stack": "MiniMax H3 + Character Swap LoRA",
    },
}
DEFAULT_ENGINE = "ltx25-ripple"

# The application asks for "Arial Narrow" then Aptos Display; Liberation Sans Narrow is the
# metric-compatible face actually installed, and DejaVu Sans stands in for Inter.
DISPLAY_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/liberation/LiberationSansNarrow-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
BODY_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)

# Square ratios: the ambient glow sits where body::before puts it, at 76% across and 10% down.
GLOW_AT = (0.76, 0.10)
GLOW_RADIUS = 416          # 26rem
GLOW_TIGHT_RADIUS = 168
FRAME_RADIUS = 28          # --radius-md at this canvas scale

# Social candidate only: leave the established stacked/wipe layouts unchanged.
SOCIAL = {
    "masthead_y": 82,
    "reality": {"y": 346, "size": 104},
    "swap": {"y": 446, "size": 112, "reveal_lift": 8},
    "subtitle": {"y": 574, "size": 22},
    "passport": {"x": 120, "y": 1345, "width": 840, "height": 190,
                 "size": 38, "text": "YOUR CHARACTER. YOUR MOMENT."},
}


def _first_existing(candidates):
    for path in candidates:
        if Path(path).is_file():
            return path
    return "Sans"


def fonts():
    return {"display": _first_existing(DISPLAY_FONT_CANDIDATES),
            "body": _first_existing(BODY_FONT_CANDIDATES)}


def theme(engine):
    return ENGINES.get(engine, ENGINES[DEFAULT_ENGINE])


# --- tiny image writers, so no image library is needed --------------------------------------
def _write_pgm(path, width, height, values):
    with open(path, "wb") as handle:
        handle.write(f"P5\n{width} {height}\n255\n".encode())
        handle.write(bytes(values))


def _write_pam_rgba(path, width, height, values):
    with open(path, "wb") as handle:
        handle.write(f"P7\nWIDTH {width}\nHEIGHT {height}\nDEPTH 4\nMAXVAL 255\n"
                     "TUPLTYPE RGB_ALPHA\nENDHDR\n".encode())
        handle.write(bytes(values))


def _to_png(source, target):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(source), str(target)],
                   capture_output=True, check=True)
    source.unlink(missing_ok=True)
    return target


def _rounded_alpha(x, y, width, height, radius):
    """Coverage of a rounded rectangle at one pixel, antialiased over half a pixel."""
    dx = max(radius - x, x - (width - 1 - radius), 0)
    dy = max(radius - y, y - (height - 1 - radius), 0)
    distance = math.hypot(dx, dy)
    if distance <= radius - 0.5:
        return 255
    if distance >= radius + 0.5:
        return 0
    return int(255 * (radius + 0.5 - distance))


def _rounded_mask(width, height, radius):
    return bytes(_rounded_alpha(x, y, width, height, radius)
                 for y in range(height) for x in range(width))


def _blend(base, accent, alpha):
    return tuple(int(round(b + (a - b) * alpha)) for b, a in zip(base, accent))


def _background(width, height, accent, soft, glow, small=(270, 480)):
    """The flat background plus the two ambient glows, computed small and upscaled."""
    scale_x, scale_y = small[0] / width, small[1] / height
    centre_x, centre_y = GLOW_AT[0] * small[0], GLOW_AT[1] * small[1]
    radii = (GLOW_RADIUS * scale_x, GLOW_TIGHT_RADIUS * scale_x)
    pixels = bytearray()
    for y in range(small[1]):
        for x in range(small[0]):
            distance = math.hypot(x - centre_x, y - centre_y)
            alpha = soft * max(0.0, 1.0 - distance / radii[0])
            alpha += glow * max(0.0, 1.0 - distance / radii[1])
            pixels.extend(_blend(BASE["bg"], accent, min(1.0, alpha)))
    return pixels, small


def _passport_card(width, height, accent):
    """Alpha artwork for a collectible Take Passport card, matching the studio's surface tokens."""
    outer = _rounded_mask(width, height, 24)
    inset = _inset_coverage(width, height, 24, inset=2)
    rgba = bytearray()
    for y in range(height):
        for x in range(width):
            i = y * width + x
            coverage = outer[i]
            if not coverage:
                rgba.extend((0, 0, 0, 0))
                continue
            border = coverage > inset[i]
            if x < 6:
                colour = accent
            elif border:
                colour = accent
            elif y < 3:
                colour = _blend(BASE["surface"], accent, 0.20)
            else:
                colour = BASE["surface"]
            alpha = int(round(242 * coverage / 255))
            rgba.extend((*colour, alpha))
    return rgba


def ensure_assets(cache_dir, engine, labels=("SOURCE", "SWAP"), label_ink=None,
                  label_size=30, band=(992, 558)):
    """Generate the static artwork for one engine, once, and return the paths.

    label_ink is the measured ink width of each label: a chip has to hug its text, and guessing
    the advance width is what makes a chip look wrong.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    palette = theme(engine)
    accent = palette["accent"]
    values = {"background": cache_dir / f"reel-bg-{engine}.png"}
    if not values["background"].is_file():
        pixels, small = _background(1080, 1920, accent, palette["accent_soft"],
                                    palette["accent_glow"])
        raw = cache_dir / f"reel-bg-{engine}.ppm"
        with open(raw, "wb") as handle:
            handle.write(f"P6\n{small[0]} {small[1]}\n255\n".encode())
            handle.write(bytes(pixels))
        big = cache_dir / f"reel-bg-{engine}-big.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-vf",
                        "scale=1080:1920:flags=bicubic", str(big)], capture_output=True, check=True)
        raw.unlink(missing_ok=True)
        _to_png(big, values["background"])

    band_width, band_height = band
    mask = cache_dir / f"reel-band-mask-{band_width}x{band_height}.png"
    if not mask.is_file():
        pgm = cache_dir / f"reel-band-mask-{band_width}x{band_height}.pgm"
        _write_pgm(pgm, band_width, band_height,
                   _rounded_mask(band_width, band_height, FRAME_RADIUS))
        _to_png(pgm, mask)
    values["band_mask"] = mask

    outline = cache_dir / f"reel-band-outline-{band_width}x{band_height}.png"
    if not outline.is_file():
        outer = _rounded_mask(band_width, band_height, FRAME_RADIUS)
        inset = _inset_coverage(band_width, band_height, FRAME_RADIUS)
        rgba = bytearray()
        for i, coverage in enumerate(outer):
            border = max(0, coverage - inset[i])
            rgba.extend((0xFF, 0xFF, 0xFF,
                         int(round(BASE["line_alpha"] * 255 * border / 255))))
        pam = cache_dir / f"reel-band-outline-{band_width}x{band_height}.pam"
        _write_pam_rgba(pam, band_width, band_height, rgba)
        _to_png(pam, outline)
    values["band_outline"] = outline

    if label_ink:
        for name, ink in zip(labels, label_ink):
            chip = cache_dir / f"reel-chip-{name.lower()}.png"
            width, height = ink + 48, label_size + 26
            outer = _rounded_mask(width, height, height // 2)
            inset = _inset_coverage(width, height, height // 2)
            rgba = bytearray()
            for i, coverage in enumerate(outer):
                if coverage == 0:
                    rgba.extend((0, 0, 0, 0))
                    continue
                # The application's chip: a dark fill (rgba(8,8,11,.78)) inside a 1px
                # rgba(255,255,255,.10) border. Pre-blended, so no double alpha.
                colour = (_blend(BASE["stage"], (0xFF, 0xFF, 0xFF), BASE["line_alpha"])
                          if inset[i] < coverage else BASE["stage"])
                rgba.extend((*colour, 199))
            pam = cache_dir / f"reel-chip-{name.lower()}.pam"
            _write_pam_rgba(pam, width, height, rgba)
            _to_png(pam, chip)
            values[f"chip_{name.lower()}"] = chip
    ticket = cache_dir / f"reel-passport-ticket-v1-{engine}.png"
    if not ticket.is_file():
        width, height = SOCIAL["passport"]["width"], SOCIAL["passport"]["height"]
        pam = cache_dir / f"reel-passport-ticket-v1-{engine}.pam"
        _write_pam_rgba(pam, width, height, _passport_card(width, height, palette["accent"]))
        _to_png(pam, ticket)
    values["passport_ticket"] = ticket
    return values


def _inset_coverage(width, height, radius, inset=1):
    """Coverage of the rectangle shrunk by `inset` pixels, expressed on the full-size grid."""
    inner_width, inner_height = width - 2 * inset, height - 2 * inset
    inner = _rounded_mask(inner_width, inner_height, max(0, radius - inset))
    coverage = bytearray(width * height)
    for y in range(inset, height - inset):
        row = y * width
        inner_row = (y - inset) * inner_width
        for x in range(inset, width - inset):
            coverage[row + x] = inner[inner_row + x - inset]
    return coverage
