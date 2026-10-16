"""Output assembly preserves source audio and builds local social artifacts."""
from pathlib import Path
import subprocess
from media import ffprobe

_REEL_FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def restore_source_audio(rendered: str, source: str, output: Path) -> str:
    """Keep edited video and optional original audio, bounded by edited duration."""
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(rendered), "-i", str(source),
        "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "copy", "-c:a", "aac",
        "-b:a", "192k", "-t", str(ffprobe(rendered)["duration"]),
        "-movflags", "+faststart", str(output),
    ], capture_output=True, check=True, timeout=180)
    return str(output.resolve())


def build_comparison_reel(source: str | Path, result: str | Path, output: Path) -> str:
    """Render a truthful 9:16 local comparison MP4 from synchronized source/result clips."""
    source, result, output = Path(source), Path(result), Path(output)
    result_info = ffprobe(result)
    duration, fps = result_info["duration"], result_info["fps"]
    if duration <= 0:
        raise ValueError("Result video must have a positive duration")
    output.parent.mkdir(parents=True, exist_ok=True)
    font = str(_REEL_FONT) if _REEL_FONT.is_file() else "Sans"
    panel = "scale=960:540:force_original_aspect_ratio=decrease,pad=960:540:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
    filters = (
        f"[0:v]{panel}[source];[1:v]{panel}[result];"
        f"color=c=0c0c10:s=1080x1920:d={duration}[canvas];"
        "[canvas][source]overlay=60:300[stacked];[stacked][result]overlay=60:1120,"
        "drawbox=x=60:y=240:w=960:h=600:color=white@0.16:t=2,"
        "drawbox=x=60:y=1060:w=960:h=600:color=white@0.16:t=2,"
        f"drawtext=fontfile={font}:text=ORIGINAL:fontcolor=white:fontsize=38:x=60:y=170,"
        f"drawtext=fontfile={font}:text=RECAST:fontcolor=white:fontsize=38:x=60:y=990,"
        f"drawtext=fontfile={font}:text=OpenGenjutsu local comparison:fontcolor=white@0.62:fontsize=24:x=(w-text_w)/2:y=1770[out]"
    )
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(source), "-i", str(result),
        "-filter_complex", filters, "-map", "[out]", "-map", "1:a:0?",
        "-t", str(duration), "-r", str(fps), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output),
    ], capture_output=True, check=True, timeout=300)
    return str(output.resolve())
