"""Filesystem, model names and local pipeline defaults."""
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent.parent
WORK = Path(os.environ.get("OPENGENJUTSU_WORK", ROOT / "work"))
WORK.mkdir(parents=True, exist_ok=True)
( WORK / "jobs").mkdir(exist_ok=True)
(WORK / "media").mkdir(exist_ok=True)

COMFY_BASE_URL = os.environ.get("COMFY_BASE_URL", "http://127.0.0.1:8189")

# model files (see README > Models)
F_UNET_KLEIN = "flux-2-klein-9b-fp8.safetensors"
F_CLIP_KLEIN = "qwen_3_8b_fp8mixed.safetensors"
F_VAE_KLEIN = "full_encoder_small_decoder.safetensors"

F_UNET_LTX = "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"
F_CLIP_LTX = "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors"
F_VAE_VID = "ltx-2.5-video-vae-conv-bf16.safetensors"
F_VAE_AUD = "ltx-2.5-audio-vae-bf16.safetensors"
F_LORA_RIPPLE = "LTX25_Ripple_v11.safetensors"

NEG_VIDEO = ("blurry, low resolution, ugly, garbled mess, compression artifacts, "
             "glitch, stop motion, still image, pixelated, robotic voice, oversaturated")

RIPPLE_PROMPT = ("A cinematic tracking shot follows the action. "
                 "Use the reference video for motion, timing, camera movement, "
                 "composition, and unchanged scene content, while consistently "
                 "propagating the visual edit established in the first frame "
                 "throughout the video. Maintain sharp detail on armor, fur, "
                 "and foliage. Preserve natural lighting and depth of field.")

