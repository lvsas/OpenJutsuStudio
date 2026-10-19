"""Output assembly preserves source audio and builds local social artifacts."""
from pathlib import Path
import subprocess

from media import ffprobe
from reel_design import (BASE, DEFAULT_ENGINE, ENGINES, ensure_assets, fonts,
                         theme as design_theme)

# The reel palette is the application's palette; it lives in reel_design next to the tokens it
# mirrors, so a studio's colour is defined once.
DEFAULT_REEL_ENGINE = DEFAULT_ENGINE


def _hex(rgb):
    return "0x%02X%02X%02X" % tuple(rgb)

# Vertical layout for a 1080x1920 frame, in the visual language of the application: the
# wordmark and accent rule of its header, a tracked eyebrow, a condensed display line, and the
# video set into a rounded surface with a hairline border.
SAFE_BOTTOM = 1560
BRAND = {"font_size": 54, "open_x": 352, "name_x": 487, "rule_w": 372}
MASTHEAD = {"rule_gap": 70, "rule_h": 2, "eyebrow_gap": 108, "eyebrow_size": 24}
EYEBROW = "C H A R A C T E R  S W A P"
MICRO = "OpenGenjutsu · local comparison"
LABELS = ("SOURCE", "SWAP")
# Chips hug their text, so the ink widths are measured rather than estimated; see the note on
# the wordmark in the skill, the same rule applies to a capsule.
CHIP = {"margin": 20, "size": 30, "height": 56, "pad": 48, "ink": (104, 72)}
STACKED = {
    "masthead_y": 120,
    "panel": {"x": 60, "width": 960, "height": 540, "source_y": 280, "result_y": 886},
    "micro": {"y": 1454, "size": 26, "second_y": 1486, "second_size": 24},
}

# The wipe layout: one rounded band where the result replaces the source, so the change reads as
# a single movement rather than as two pictures to compare. The y values already balance the
# card inside the area a feed leaves free, so the composition's centre lands near y=780.
WIPE = {
    "masthead_y": 258,
    "hook": {"y": 446, "size": 68, "leading": 66},
    "band": {"x": 44, "y": 646, "width": 992, "height": 558},
    "micro": {"y": 1242, "size": 26, "second_y": 1278, "second_size": 24},
    "edge": 5,
}
HOOK = ("SAME MOMENT.", "NEW CHARACTER.")
LAYOUTS = ("stacked", "wipe")
WIPE_HOLD_RATIO, WIPE_MAX_HOLD = 0.15, 0.4
WIPE_SWEEP_RATIO, WIPE_MAX_SWEEP, WIPE_MIN_SWEEP = 0.4, 1.2, 0.3


REEL_MODES = ("compact", "standard", "extended")


def reel_timeline(duration, fps, frames):
    """Return frame-aligned narrative beats for a complete generated take.

    Result frames are authoritative. Durations determine only the opening story;
    everything after Collect remains the real result, uncut.
    """
    if fps <= 0 or frames < 3 or duration <= 0:
        raise ValueError("Reel timeline needs a positive duration, FPS and at least 3 frames")
    real_duration = frames / fps
    if real_duration < 2.5:
        mode, capture_s, recast_s = "compact", max(0.25 * real_duration, 0.35), max(0.30 * real_duration, 0.40)
    elif real_duration <= 8.0:
        mode = "standard"
        capture_s = min(1.25, max(0.85, 0.28 * real_duration))
        recast_s = min(1.20, max(0.80, 0.30 * real_duration))
    else:
        mode, capture_s, recast_s = "extended", 1.25, 1.20
    capture_end = max(1, min(frames - 2, round(capture_s * fps)))
    recast_end = max(capture_end + 1, min(frames - 1, capture_end + round(recast_s * fps)))
    return {"mode": mode, "frame_count": frames, "fps": fps,
            "capture_start_frame": 0, "capture_end_frame": capture_end,
            "recast_end_frame": recast_end, "collect_start_frame": recast_end,
            "capture_end": capture_end / fps, "recast_end": recast_end / fps,
            "recast_duration": (recast_end - capture_end) / fps}


def validate_reel_media(source, result):
    """Reject incompatible comparison inputs instead of freezing or inventing pixels."""
    source_info, result_info = ffprobe(source), ffprobe(result)
    if abs(source_info["fps"] - result_info["fps"]) > 0.001:
        raise ValueError("Comparison source and result must have the same FPS")
    if source_info["frames"] < result_info["frames"]:
        raise ValueError("Comparison source is shorter than result; refusing to invent source frames")
    return source_info, result_info



def wipe_timing(duration):
    """Hold the source for a beat, then sweep. Bounded so a short clip still has both."""
    hold = min(WIPE_MAX_HOLD, max(0.0, duration) * WIPE_HOLD_RATIO)
    sweep = min(WIPE_MAX_SWEEP, max(WIPE_MIN_SWEEP, max(0.0, duration) * WIPE_SWEEP_RATIO))
    if hold + sweep >= duration:
        sweep = max(WIPE_MIN_SWEEP, duration - hold - 0.05)
    return round(hold, 3), round(sweep, 3)


def wipe_label_timing(duration):
    """Keep each chip on the pixels its label names during the right-to-left reveal."""
    hold, sweep = wipe_timing(duration)
    band = WIPE["band"]
    source_right = CHIP["margin"] + CHIP["ink"][0] + CHIP["pad"]
    swap_left = band["width"] - CHIP["margin"] - CHIP["ink"][1] - CHIP["pad"]
    source_until = hold + sweep * (1 - source_right / band["width"])
    swap_from = hold + sweep * (1 - swap_left / band["width"])
    return round(source_until, 3), round(swap_from, 3)


def reel_theme(engine):
    """Theme for an engine, falling back to the default rather than failing a share."""
    return design_theme(engine)


def restore_source_audio(rendered: str, source: str, output: Path) -> str:
    """Keep edited video and optional original audio, bounded by edited duration."""
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(rendered), "-i", str(source),
        "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "copy", "-c:a", "aac",
        "-b:a", "192k", "-t", str(ffprobe(rendered)["duration"]),
        "-movflags", "+faststart", str(output),
    ], capture_output=True, check=True, timeout=180)
    return str(output.resolve())


def _centred(font, text, y, colour, size, extra=""):
    return (f"drawtext=fontfile={font}:text={text}:fontcolor={colour}:fontsize={size}:"
            f"x=(w-text_w)/2:y={y}{extra}")


def _masthead(font, theme, y, eyeline=EYEBROW):
    """The application header: two-tone wordmark, accent rule, tracked eyebrow."""
    accent = _hex(theme["accent"])
    return [
        f"drawtext=fontfile={font['display']}:text=OPEN:fontcolor={_hex(BASE['text'])}:"
        f"fontsize={BRAND['font_size']}:x={BRAND['open_x']}:y={y}",
        f"drawtext=fontfile={font['display']}:text=GENJUTSU:fontcolor={accent}:"
        f"fontsize={BRAND['font_size']}:x={BRAND['name_x']}:y={y}",
        f"drawbox=x={BRAND['open_x']}:y={y + MASTHEAD['rule_gap']}:w={BRAND['rule_w']}:"
        f"h={MASTHEAD['rule_h']}:color={accent}@0.7:t=fill",
        _centred(font["display"], eyeline, y + MASTHEAD["eyebrow_gap"], accent,
                 MASTHEAD["eyebrow_size"]),
    ]


ASSET_ORDER = ("background", "band_mask", "band_outline", "chip_source", "chip_swap")
REEL_ASSET_DIR = Path(__file__).resolve().parents[1] / "work" / "reel-assets"


def _faces(font):
    """Accept a font mapping or a single path, so a builder stays callable with either."""
    return font if isinstance(font, dict) else {"display": font, "body": font}


def _asset_inputs(assets):
    names = [name for name in ASSET_ORDER if name in assets]
    return [assets[name] for name in names], {name: 2 + i for i, name in enumerate(names)}


def _default_inputs():
    return {name: 2 + i for i, name in enumerate(ASSET_ORDER)}


def _chip_overlay(inputs, label, x, y, in_label, out_label="chips", enable=None, fps=24):
    """The capsule artwork on top of the frame. An input, because ffmpeg cannot round a corner.

    A named output ends its chain, so this always starts a new one with its own input label:
    continuing implicitly after `[name]` is rejected as too many inputs for overlay.
    """
    gate = f":enable='{enable}'" if enable else ""
    return (f"[{in_label}][{inputs['chip_' + label.lower()]}:v]"
            f"overlay={x}:{y}{gate}[{out_label}]")


def _chip_label(faces, label, x, y, enable=None):
    """The word inside the capsule, in the application's warm text colour rather than accent."""
    gate = f":enable='{enable}'" if enable else ""
    return (f"drawtext=fontfile={faces['display']}:text={label}:"
            f"fontcolor={_hex(BASE['text'])}:fontsize={CHIP['size']}:"
            f"x={x + CHIP['pad'] // 2 - 1}:"
            f"y={y + (CHIP['height'] - CHIP['size']) // 2 - 2}{gate}")


def _micro(faces, theme, layout):
    """The muted description under the frame: what this is, and what made it."""
    micro = layout["micro"]
    return [
        _centred(faces["body"], MICRO, micro["y"], _hex(BASE["subtle"]), micro["size"]),
        _centred(faces["body"], theme["stack"], micro["second_y"], _hex(BASE["subtle"]),
                 micro["second_size"]),
    ]


def reel_filters(duration, font, engine=DEFAULT_REEL_ENGINE, inputs=None, fps=24):
    """The stacked layout: both halves visible at once, for reading rather than watching."""
    faces, theme = _faces(font), reel_theme(engine)
    inputs = inputs or _default_inputs()
    accent, bg = _hex(theme["accent"]), _hex(BASE["bg"])
    layout, panel, chip = STACKED, STACKED["panel"], CHIP
    geo = (f"scale={panel['width']}:{panel['height']}:force_original_aspect_ratio=decrease,"
           f"pad={panel['width']}:{panel['height']}:(ow-iw)/2:(oh-ih)/2:black,setsar=1")
    mask, outline = inputs["band_mask"], inputs["band_outline"]
    chip_x, chip_y = panel["x"] + chip["margin"], panel["source_y"] + chip["margin"]
    swap_x, swap_y = panel["x"] + chip["margin"], panel["result_y"] + chip["margin"]
    texts = [
        *_masthead(faces, theme, layout["masthead_y"]),
        _centred(faces["display"], "▼", panel["source_y"] + panel["height"] + 14, accent, 46),
        _chip_label(faces, "SOURCE", chip_x, chip_y),
        _chip_label(faces, "SWAP", swap_x, swap_y),
        *_micro(faces, theme, layout),
    ]
    groups = [
        f"[0:v]{geo}[src]",
        f"[1:v]{geo}[res]",
        f"[src][{mask}:v]alphamerge[src_r]",
        f"[res][{mask}:v]alphamerge[res_r]",
        f"color=c={bg}:s=1080x1920:d={duration}[base]",
        f"[base][{inputs['background']}:v]overlay=0:0[canvas]",
        f"[canvas][src_r]overlay={panel['x']}:{panel['source_y']}[p1]",
        f"[p1][{outline}:v]overlay={panel['x']}:{panel['source_y']}[p1o]",
        f"[p1o][res_r]overlay={panel['x']}:{panel['result_y']}[p2]",
        f"[p2][{outline}:v]overlay={panel['x']}:{panel['result_y']}[p2o]",
        _chip_overlay(inputs, "SOURCE", chip_x, chip_y, "p2o", out_label="withsource"),
        _chip_overlay(inputs, "SWAP", swap_x, swap_y, "withsource"),
        f"[chips]{','.join(texts)}[out]",
    ]
    return ";".join(groups)


def wipe_filters(duration, font, engine=DEFAULT_REEL_ENGINE, inputs=None, fps=24, timeline=None):
    """The wipe layout: one band where the result replaces the source in a single movement.

    The result stays still and is revealed under a growing alpha mask, so the change reads as
    one image being replaced rather than as two pictures to compare. crop() cannot do this: its
    width is evaluated once at init, where t is unavailable, so an animated mask is the only way
    to get a real wipe instead of a slide. Everything derives from the clip's own duration.
    """
    faces, theme = _faces(font), reel_theme(engine)
    inputs = inputs or _default_inputs()
    accent, bg = _hex(theme["accent"]), _hex(BASE["bg"])
    layout, band, chip = WIPE, WIPE["band"], CHIP
    if timeline is None:
        hold, sweep = wipe_timing(duration)
    else:
        hold, sweep = timeline["capture_end"], timeline["recast_duration"]
    # Even boundary positions keep the subject frame encoder-safe for yuv420p.
    progress = f"max(0,min(1,(t-{hold})/{sweep}))"
    blend_progress = f"max(0,min(1,(T-{hold})/{sweep}))"
    inside_x = f"({band['width']}-(2*floor({band['width'] // 2}*{progress})))"
    blend_inside_x = f"({band['width']}-(2*floor({band['width'] // 2}*{blend_progress})))"
    geo = (f"scale={band['width']}:{band['height']}:force_original_aspect_ratio=decrease,"
           f"pad={band['width']}:{band['height']}:(ow-iw)/2:(oh-ih)/2:black,setsar=1")
    mask, outline = inputs["band_mask"], inputs["band_outline"]
    chip_y = band["y"] + chip["margin"]
    chip_x = band["x"] + chip["margin"]
    swap_at = band["x"] + band["width"] - chip["margin"] - (CHIP["ink"][1] + chip["pad"])
    source_until, swap_from = wipe_label_timing(duration)
    source_gate = f"lt(t,{source_until})"
    swap_gate = f"gte(t,{swap_from})"
    hook = layout["hook"]
    texts = [
        *_masthead(faces, theme, layout["masthead_y"]),
        _centred(faces["display"], HOOK[0], hook["y"], _hex(BASE["text"]), hook["size"]),
        _centred(faces["display"], HOOK[1], hook["y"] + hook["leading"], accent, hook["size"]),
        _chip_label(faces, "SOURCE", chip_x, chip_y, enable=source_gate),
        # SWAP begins only once its whole chip is on revealed result pixels.
        _chip_label(faces, "SWAP", swap_at, chip_y, enable=swap_gate),
        *_micro(faces, theme, layout),
    ]
    groups = [
        f"[0:v]{geo}[src]",
        f"[1:v]{geo}[res]",
        # crop() cannot do this: its width is evaluated once at init, where t is unavailable.
        # The animated overlay carries only the existing narrow accent edge; blend below selects
        # the source/result pixels for every other position.
        f"color=c={accent}:s={WIPE['edge']}x{band['height']}:r={fps}[mark]",
        # The moving edge travels inside the band. blend selects the unaltered source until the
        # edge reaches each pixel, then selects the result; the rounded alpha is applied only to
        # that completed source/result frame.
        f"[res][mark]overlay=x='{inside_x}':y=0[resmarked]",
        f"[src][resmarked]blend=all_expr='if(gte(X,{blend_inside_x}),B,A)'[transition]",
        f"[transition][{mask}:v]alphamerge[transition_rounded]",
        f"color=c={bg}:s=1080x1920:d={duration}[base]",
        f"[base][{inputs['background']}:v]overlay=0:0[canvas]",
        f"[canvas][transition_rounded]overlay={band['x']}:{band['y']}[barred]",
        f"[barred][{outline}:v]overlay={band['x']}:{band['y']}[outlined]",
        _chip_overlay(inputs, "SOURCE", chip_x, chip_y, "outlined", out_label="withsource",
                      enable=source_gate),
        _chip_overlay(inputs, "SWAP", swap_at, chip_y, "withsource", enable=swap_gate),
        f"[chips]{','.join(texts)}[out]",
    ]
    return ";".join(groups)


def build_comparison_reel(source: str | Path, result: str | Path, output: Path,
                          engine: str = DEFAULT_REEL_ENGINE,
                          layout: str = "stacked") -> str:
    """Render a truthful 9:16 local comparison MP4 from synchronized source/result clips."""
    source, result, output = Path(source), Path(result), Path(output)
    if layout not in LAYOUTS:
        raise ValueError(f"Unknown reel layout: {layout}")
    _, result_info = validate_reel_media(source, result)
    duration, fps, frame_count = result_info["duration"], result_info["fps"], result_info["frames"]
    if duration <= 0:
        raise ValueError("Result video must have a positive duration")
    timeline = reel_timeline(duration, fps, frame_count)
    output.parent.mkdir(parents=True, exist_ok=True)
    band = WIPE["band"] if layout == "wipe" else STACKED["panel"]
    assets = ensure_assets(REEL_ASSET_DIR, engine, labels=LABELS, label_ink=CHIP["ink"],
                           label_size=CHIP["size"],
                           band=(band["width"], band["height"]))
    asset_paths, inputs = _asset_inputs(assets)
    filters = (wipe_filters(duration, fonts(), engine, inputs, fps=fps, timeline=timeline)
               if layout == "wipe" else reel_filters(duration, fonts(), engine, inputs, fps=fps))
    command = ["ffmpeg", "-y", "-v", "error", "-i", str(source), "-i", str(result)]
    for path in asset_paths:
        command += ["-loop", "1", "-framerate", str(fps), "-i", str(path)]
    command += ["-filter_complex", filters,
                "-map", "[out]", "-map", "1:a:0?",
                "-frames:v", str(frame_count), "-t", str(duration), "-r", str(fps), "-c:v", "libx264", "-preset", "medium",
                "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", str(output)]
    subprocess.run(command, capture_output=True, check=True, timeout=300)
    return str(output.resolve())
