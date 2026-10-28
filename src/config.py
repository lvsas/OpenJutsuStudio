"""Filesystem, model names and local pipeline defaults."""
from pathlib import Path
import os
from model_defaults import (
    F_UNET_KLEIN, F_CLIP_KLEIN, F_VAE_KLEIN, F_UNET_LTX, F_CLIP_LTX,
    F_VAE_VID, F_VAE_AUD, F_LORA_RIPPLE,
)

ROOT = Path(__file__).resolve().parent.parent
WORK = Path(os.environ.get("OPENGENJUTSU_WORK", ROOT / "work"))
WORK.mkdir(parents=True, exist_ok=True)
( WORK / "jobs").mkdir(exist_ok=True)
(WORK / "media").mkdir(exist_ok=True)

LOCAL_COMFY_PROXY_URL = "http://127.0.0.1:8189"


def compute_target():
    """Saved explicit settings win; otherwise use the app override/local default."""
    from compute_settings import Store
    return Store(WORK).current()


def comfy_base_url() -> str:
    """Resolve without mutating the SDK environment or trusting an ambient target."""
    return compute_target().base_url


# Legacy declared default; actual clients resolve a fresh, explicit target.
COMFY_BASE_URL = LOCAL_COMFY_PROXY_URL

NEG_VIDEO = ("blurry, low resolution, ugly, garbled mess, compression artifacts, "
             "glitch, stop motion, still image, pixelated, robotic voice, oversaturated")

# Content-neutral model-card default; do not inject a test clip's scene or objects.
RIPPLE_PROMPT = ("Use the reference video for motion, timing, camera movement, "
                 "composition, and unchanged scene content, while consistently "
                 "propagating the visual edit established in the first frame "
                 "throughout the video.")

