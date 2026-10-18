"""Output assembly preserves source audio and builds local social artifacts."""
from pathlib import Path
import subprocess
from media import ffprobe

_REEL_FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

# One reel theme per studio, so a shared clip carries the colour of the engine that made it.
REEL_THEMES = {
    "ltx25-ripple": {
        "accent": "0xD8FF3E",
        "engine": "Character Swap · FLUX 2 Klein + LTX 2.5 + Ripple",
    },
    "minimax-h3": {
        "accent": "0xFF4F2E",
        "engine": "Character Swap · MiniMax H3 + Character Swap LoRA",
    },
}
DEFAULT_REEL_ENGINE = "ltx25-ripple"

# Vertical layout for a 1080x1920 frame. Platforms draw their caption, account and buttons
# over the bottom of a vertical video, so nothing that matters may sit below this line.
SAFE_BOTTOM = 1560
BRAND = {"font_size": 46, "y": 132, "open_x": 334, "name_x": 485, "rule_y": 192, "rule_w": 408}
PANELS = {"x": 60, "width": 960, "height": 540, "source_y": 272, "result_y": 896}
LABEL = {"font_size": 44, "x": 84, "offset": 22, "box_border": 14}


def reel_theme(engine):
    """Theme for an engine, falling back to the default rather than failing a share."""
    return REEL_THEMES.get(engine, REEL_THEMES[DEFAULT_REEL_ENGINE])


def restore_source_audio(rendered: str, source: str, output: Path) -> str:
    """Keep edited video and optional original audio, bounded by edited duration."""
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(rendered), "-i", str(source),
        "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "copy", "-c:a", "aac",
        "-b:a", "192k", "-t", str(ffprobe(rendered)["duration"]),
        "-movflags", "+faststart", str(output),
    ], capture_output=True, check=True, timeout=180)
    return str(output.resolve())


def reel_filters(duration, font, engine=DEFAULT_REEL_ENGINE):
    """The filtergraph for the 9:16 comparison reel.

    Kept separate from the render so the layout can be asserted without encoding a video.
    Three constraints drive it: the panels are labelled in place so the reading is instant,
    the brand sits where a feed does not cover it, and everything stays above SAFE_BOTTOM.
    """
    theme = reel_theme(engine)
    accent = theme["accent"]
    brand, panels, label = BRAND, PANELS, LABEL
    panel = (f"scale={panels['width']}:{panels['height']}:force_original_aspect_ratio=decrease,"
             f"pad={panels['width']}:{panels['height']}:(ow-iw)/2:(oh-ih)/2:black,setsar=1")
    label_y = {key: panels[key] + label["offset"] for key in ("source_y", "result_y")}
    label_box = f"box=1:boxcolor=black@0.55:boxborderw={label['box_border']}"
    arrow_y = panels["source_y"] + panels["height"] + 18

    def cap(text, y, colour, size, extra=""):
        return (f"drawtext=fontfile={font}:text={text}:fontcolor={colour}:fontsize={size}:"
                f"x=(w-text_w)/2:y={y}{extra}")

    tail = [
        # Frames keep the two halves distinguishable on any footage.
        f"drawbox=x={panels['x']}:y={panels['source_y']}:w={panels['width']}:"
        f"h={panels['height']}:color={accent}@0.35:t=2",
        f"drawbox=x={panels['x']}:y={panels['result_y']}:w={panels['width']}:"
        f"h={panels['height']}:color={accent}@0.35:t=2",
        # Brand, in the two tones of the application header.
        f"drawtext=fontfile={font}:text=OPEN:fontcolor=white:fontsize={brand['font_size']}:"
        f"x={brand['open_x']}:y={brand['y']}",
        f"drawtext=fontfile={font}:text=GENJUTSU:fontcolor={accent}:"
        f"fontsize={brand['font_size']}:x={brand['name_x']}:y={brand['y']}",
        f"drawbox=x={brand['open_x']}:y={brand['rule_y']}:w={brand['rule_w']}:h=3:"
        f"color={accent}@0.7:t=fill",
        cap(theme["engine"], 212, "white@0.78", 24),
        # Panel labels sit on the image itself, large enough to read in a feed.
        f"drawtext=fontfile={font}:text=SOURCE:fontcolor={accent}:fontsize={label['font_size']}:"
        f"x={label['x']}:y={label_y['source_y']}:{label_box}",
        f"drawtext=fontfile={font}:text=SWAP:fontcolor={accent}:fontsize={label['font_size']}:"
        f"x={label['x']}:y={label_y['result_y']}:{label_box}",
        # What separates the two panels, so the before/after reads at a glance.
        cap("▼", arrow_y, accent, 52),
        cap("OpenGenjutsu · local comparison", 1470, "white@0.6", 26),
    ]
    return (
        f"[0:v]{panel}[source];[1:v]{panel}[result];"
        f"color=c=0x101014:s=1080x1920:d={duration}[canvas];"
        f"[canvas][source]overlay={panels['x']}:{panels['source_y']}[stacked];"
        f"[stacked][result]overlay={panels['x']}:{panels['result_y']}," + ",".join(tail) + "[out]"
    )


def build_comparison_reel(source: str | Path, result: str | Path, output: Path,
                          engine: str = DEFAULT_REEL_ENGINE) -> str:
    """Render a truthful 9:16 local comparison MP4 from synchronized source/result clips."""
    source, result, output = Path(source), Path(result), Path(output)
    result_info = ffprobe(result)
    duration, fps = result_info["duration"], result_info["fps"]
    if duration <= 0:
        raise ValueError("Result video must have a positive duration")
    output.parent.mkdir(parents=True, exist_ok=True)
    font = str(_REEL_FONT) if _REEL_FONT.is_file() else "Sans"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(source), "-i", str(result),
        "-filter_complex", reel_filters(duration, font, engine), "-map", "[out]", "-map", "1:a:0?",
        "-t", str(duration), "-r", str(fps), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output),
    ], capture_output=True, check=True, timeout=300)
    return str(output.resolve())
