"""Output assembly preserves source audio and builds local social artifacts."""
from pathlib import Path
import subprocess
from media import ffprobe

_REEL_FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

# One reel theme per studio, so a shared clip carries the colour of the engine that made it.
REEL_THEMES = {
    "ltx25-ripple": {"accent": "0xD8FF3E", "engine": "LTX 2.5 + Ripple"},
    "minimax-h3": {"accent": "0xFF4F2E", "engine": "MiniMax H3"},
}
DEFAULT_REEL_ENGINE = "ltx25-ripple"


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

    Kept separate from the render so the labelling and the engine colour can be asserted
    without encoding a video. A shared clip has to read correctly at a glance, so the
    labels say what the two panels are and the accent says which studio produced it.
    """
    theme = reel_theme(engine)
    accent = theme["accent"]
    panel = ("scale=960:540:force_original_aspect_ratio=decrease,"
             "pad=960:540:(ow-iw)/2:(oh-ih)/2:black,setsar=1")
    return (
        f"[0:v]{panel}[source];[1:v]{panel}[result];"
        f"color=c=0x101014:s=1080x1920:d={duration}[canvas];"
        "[canvas][source]overlay=60:300[stacked];[stacked][result]overlay=60:1120,"
        # Panels framed in the studio accent.
        f"drawbox=x=60:y=240:w=960:h=600:color={accent}@0.35:t=2,"
        f"drawbox=x=60:y=1060:w=960:h=600:color={accent}@0.35:t=2,"
        # Header: what this is, then which studio made it.
        f"drawtext=fontfile={font}:text=CHARACTER SWAP:fontcolor={accent}:fontsize=30:"
        "x=(w-text_w)/2:y=92,"
        f"drawbox=x=440:y=140:w=200:h=3:color={accent}@0.7:t=fill,"
        f"drawtext=fontfile={font}:text={theme['engine']}:fontcolor=white@0.72:fontsize=26:"
        "x=(w-text_w)/2:y=168,"
        # Panel labels.
        f"drawtext=fontfile={font}:text=SOURCE:fontcolor={accent}:fontsize=36:x=72:y=252,"
        f"drawtext=fontfile={font}:text=SWAP:fontcolor={accent}:fontsize=36:x=72:y=1072,"
        f"drawtext=fontfile={font}:text=OpenGenjutsu - local comparison:"
        "fontcolor=white@0.6:fontsize=24:x=(w-text_w)/2:y=1770[out]"
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
