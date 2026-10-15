"""
OpenGenjutsu — core engine.

Pipeline: video -> edit first frame (FLUX.2 Klein) -> propagate (LTX 2.5 + Ripple)

Everything goes through comfy-sdk, so the same code runs against:
  - a local ComfyUI behind comfy-api-proxy  (COMFY_BASE_URL=http://127.0.0.1:8189)
  - a Comfy API deployment                  (https://<dep>.run.comfy.app)
  - Comfy Cloud                             (https://cloud.comfy.org)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable

# --------------------------------------------------------------------------
# paths / config
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# scene detection
# --------------------------------------------------------------------------
def detect_scenes(video_path: str | Path, threshold: float = 0.3) -> list[dict]:
    """Detect shot boundaries using ffmpeg scene detection.

    Returns a list of segments: [{"start": int, "end": int}, ...]
    Frame indices are 0-based, inclusive.
    """
    video_path = str(video_path)

    # Get video info (fps, total frames)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate,nb_frames",
         "-of", "json", video_path],
        capture_output=True, text=True, check=True
    )
    info = json.loads(probe.stdout)
    stream = info["streams"][0]
    fps_parts = stream["r_frame_rate"].split("/")
    fps = int(fps_parts[0]) / int(fps_parts[1]) if len(fps_parts) == 2 else float(fps_parts[0])
    total_frames = int(stream.get("nb_frames", 0))

    # If nb_frames not available, estimate from duration
    if total_frames == 0:
        dur_probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", video_path],
            capture_output=True, text=True, check=True
        )
        duration = float(json.loads(dur_probe.stdout)["format"]["duration"])
        total_frames = int(duration * fps)

    # Run ffmpeg scene detection
    result = subprocess.run(
        ["ffmpeg", "-i", video_path, "-vf", f"select='gt(scene,{threshold})',showinfo",
         "-f", "null", "-"],
        capture_output=True, text=True
    )

    # Parse scene change timestamps from stderr
    cut_frames = []
    for line in result.stderr.splitlines():
        match = re.search(r"pts_time:([\d.]+)", line)
        if match:
            cut_frames.append(int(float(match.group(1)) * fps))

    # Build segments
    segments = []
    prev = 0
    for cf in cut_frames:
        if cf > prev:
            segments.append({"start": prev, "end": cf - 1})
        prev = cf
    if prev < total_frames:
        segments.append({"start": prev, "end": total_frames - 1})

    return segments


# --------------------------------------------------------------------------
# workflow builders — return NAKED graphs (what comfy-sdk expects)
# --------------------------------------------------------------------------
def build_frame_edit(image: str | dict, prompt: str, seed: int = 26416064315367,
                     steps: int = 4, cfg: float = 1.0,
                     megapixels: float = 1.0, prefix: str = "og_frame",
                     reference_image: str | dict | None = None) -> dict:
    """FLUX.2 Klein 9B image edit (distilled, 4 steps).

    If reference_image is provided, injects it as a second reference via
    LoadImage + VAEEncode + ReferenceLatent for character/persona consistency.
    """
    graph = {
        "76":  {"class_type": "LoadImage", "inputs": {"image": image}},
        "80":  {"class_type": "ImageScaleToTotalPixels",
                "inputs": {"image": ["76", 0], "upscale_method": "nearest-exact",
                           "megapixels": megapixels, "resolution_steps": 1}},
        "99":  {"class_type": "GetImageSize", "inputs": {"image": ["80", 0]}},
        "70":  {"class_type": "UNETLoader",
                "inputs": {"unet_name": F_UNET_KLEIN, "weight_dtype": "default"}},
        "71":  {"class_type": "CLIPLoader",
                "inputs": {"clip_name": F_CLIP_KLEIN, "type": "flux2", "device": "default"}},
        "72":  {"class_type": "VAELoader", "inputs": {"vae_name": F_VAE_KLEIN}},
        "74":  {"class_type": "CLIPTextEncode",
                "inputs": {"clip": ["71", 0], "text": prompt}},
        "82":  {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["74", 0]}},
        "124": {"class_type": "VAEEncode", "inputs": {"pixels": ["80", 0], "vae": ["72", 0]}},
        "125": {"class_type": "ReferenceLatent",
                "inputs": {"conditioning": ["74", 0], "latent": ["124", 0]}},
        "123": {"class_type": "ReferenceLatent",
                "inputs": {"conditioning": ["82", 0], "latent": ["124", 0]}},
        "66":  {"class_type": "EmptyFlux2LatentImage",
                "inputs": {"width": ["99", 0], "height": ["99", 1], "batch_size": 1}},
        "61":  {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "62":  {"class_type": "Flux2Scheduler",
                "inputs": {"steps": steps, "width": ["99", 0], "height": ["99", 1]}},
        "73":  {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "63":  {"class_type": "CFGGuider",
                "inputs": {"model": ["70", 0], "positive": ["125", 0],
                           "negative": ["123", 0], "cfg": cfg}},
        "64":  {"class_type": "SamplerCustomAdvanced",
                "inputs": {"noise": ["73", 0], "guider": ["63", 0],
                           "sampler": ["61", 0], "sigmas": ["62", 0],
                           "latent_image": ["66", 0]}},
        "65":  {"class_type": "VAEDecode", "inputs": {"samples": ["64", 0], "vae": ["72", 0]}},
        "9":   {"class_type": "SaveImage",
                "inputs": {"images": ["65", 0], "filename_prefix": prefix}},
    }

    # Inject reference image as second LoadImage + VAEEncode + ReferenceLatent
    if reference_image is not None:
        graph["200"] = {"class_type": "LoadImage", "inputs": {"image": reference_image}}
        graph["201"] = {"class_type": "VAEEncode",
                        "inputs": {"pixels": ["200", 0], "vae": ["72", 0]}}
        graph["202"] = {"class_type": "ReferenceLatent",
                        "inputs": {"conditioning": ["74", 0], "latent": ["201", 0]}}

    return graph


def build_ripple(video: str | dict, edited_frame: str | dict, prompt: str = RIPPLE_PROMPT,
                 frames: int = 121, seed: int = 125348341465200, fps: int = 24,
                 width: int = 1280, height: int = 704, steps: int = 16,
                 cfg: float = 1.0, strength: float = 1.2,
                 guide_strength: float = 1.0, prefix: str = "og_ripple") -> dict:
    """LTX 2.5 + Ripple FFAF IC-LoRA.

    `strength` is the key knob:
      1.35 = default; increase if the edit doesn't carry, DECREASE if the
      edit bleeds into content that should stay unchanged.
    """
    return {
        "821": {"class_type": "UNETLoader",
                "inputs": {"unet_name": F_UNET_LTX, "weight_dtype": "default"}},
        "1318": {"class_type": "CLIPLoader",
                 "inputs": {"clip_name": F_CLIP_LTX, "type": "ltxv", "device": "default"}},
        "822": {"class_type": "VAELoader", "inputs": {"vae_name": F_VAE_VID}},
        "448": {"class_type": "VAELoaderKJ",
                "inputs": {"vae_name": F_VAE_AUD, "device": "main_device",
                           "weight_dtype": "bf16"}},
        "1312": {"class_type": "LoraLoaderModelOnly",
                 "inputs": {"model": ["821", 0], "lora_name": F_LORA_RIPPLE,
                            "strength_model": strength}},
        "1320": {"class_type": "PathchSageAttentionKJ",
                 "inputs": {"model": ["1312", 0], "sage_attention": "auto",
                            "allow_compile": False}},
        "1321": {"class_type": "LTX2MemoryEfficientSageAttentionPatch",
                 "inputs": {"model": ["1320", 0], "triton_kernels": True}},
        "790": {"class_type": "VHS_LoadVideo",
                "inputs": {"video": video, "force_rate": float(fps), "custom_width": 0,
                           "custom_height": 0, "frame_load_cap": frames,
                           "skip_first_frames": 0, "select_every_nth": 1, "format": "LTXV"}},
        "782": {"class_type": "ImageResizeKJv2",
                "inputs": {"image": ["790", 0], "width": width, "height": height,
                           "upscale_method": "lanczos", "keep_proportion": "crop",
                           "pad_color": "0, 0, 0", "crop_position": "center",
                           "divisible_by": 2, "device": "cpu"}},
        "1304": {"class_type": "LoadImage", "inputs": {"image": edited_frame}},
        "1294": {"class_type": "ImageResizeKJv2",
                 "inputs": {"image": ["1304", 0], "width": width, "height": height,
                            "upscale_method": "lanczos", "keep_proportion": "crop",
                            "pad_color": "0, 0, 0", "crop_position": "center",
                            "divisible_by": 2, "device": "cpu"}},
        "1288": {"class_type": "BatchImagesNode",
                 "inputs": {"images.image0": ["1294", 0], "images.image1": ["782", 0]}},
        "1289": {"class_type": "Frames Slice",
                 "inputs": {"frames": ["1288", 0], "start": 0, "stop": frames}},
        "567": {"class_type": "EmptyLTXVLatentVideo",
                "inputs": {"width": width, "height": height, "length": frames,
                           "batch_size": 1}},
        "1257": {"class_type": "LTXVEmptyLatentAudio",
                 "inputs": {"frames_number": frames, "frame_rate": float(fps),
                            "batch_size": 1, "audio_vae": ["448", 0]}},
        "814": {"class_type": "CLIPTextEncode",
                "inputs": {"text": prompt, "clip": ["1318", 0]}},
        "388": {"class_type": "CLIPTextEncode",
                "inputs": {"text": NEG_VIDEO, "clip": ["1318", 0]}},
        "563": {"class_type": "LTXVConditioning",
                "inputs": {"positive": ["814", 0], "negative": ["388", 0],
                           "frame_rate": float(fps)}},
        "1330": {"class_type": "LTXAddVideoICLoRAGuide",
                 "inputs": {"positive": ["563", 0], "negative": ["563", 1],
                            "vae": ["822", 0], "latent": ["567", 0],
                            "image": ["1289", 0], "frame_idx": 0,
                            "strength": guide_strength,
                            "latent_downscale_factor": 1.0, "crop": "disabled",
                            "use_tiled_encode": False, "tile_size": 256,
                            "tile_overlap": 64}},
        "1259": {"class_type": "LTXVConcatAVLatent",
                 "inputs": {"video_latent": ["1330", 2], "audio_latent": ["1257", 0]}},
        "1266": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "1265": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "1319": {"class_type": "BasicScheduler",
                 "inputs": {"model": ["1321", 0], "scheduler": "simple",
                            "steps": steps, "denoise": 1.0}},
        "1267": {"class_type": "CFGGuider",
                 "inputs": {"model": ["1321", 0], "positive": ["1330", 0],
                            "negative": ["1330", 1], "cfg": cfg}},
        "1269": {"class_type": "SamplerCustomAdvanced",
                 "inputs": {"noise": ["1266", 0], "guider": ["1267", 0],
                            "sampler": ["1265", 0], "sigmas": ["1319", 0],
                            "latent_image": ["1259", 0]}},
        "423": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["1269", 0]}},
        "571": {"class_type": "LTXVCropGuides",
                "inputs": {"positive": ["1330", 0], "negative": ["1330", 1],
                           "latent": ["423", 0]}},
        "445": {"class_type": "VAEDecode",
                "inputs": {"samples": ["571", 2], "vae": ["822", 0]}},
        "815": {"class_type": "VAEDecodeAudio",
                "inputs": {"samples": ["423", 1], "vae": ["448", 0]}},
        "425": {"class_type": "VHS_VideoCombine",
                "inputs": {"images": ["445", 0], "audio": ["815", 0],
                           "frame_rate": float(fps), "loop_count": 0,
                           "filename_prefix": prefix, "format": "video/h264-mp4",
                           "pingpong": False, "save_output": True}},
    }


# --------------------------------------------------------------------------
# engines
# --------------------------------------------------------------------------
class Engine(ABC):
    """A video-editing engine. Implementations swap the model stack while the
    pipeline (edit frame 0 -> propagate) stays the same."""
    name: str = "abstract"
    label: str = "Abstract"
    requires: list[str] = []

    @abstractmethod
    def edit_frame(self, client, image: str, prompt: str, **kw) -> str:
        """Edit a still frame. Returns the stored filename."""

    @abstractmethod
    def propagate(self, client, video: str, edited_frame: str, prompt: str, **kw) -> str:
        """Propagate the frame edit across the video. Returns the output filename."""


class LTXRippleEngine(Engine):
    name = "ltx25-ripple"
    label = "LTX 2.5 + Ripple IC-LoRA"
    requires = [F_UNET_LTX, F_CLIP_LTX, F_VAE_VID, F_VAE_AUD, F_LORA_RIPPLE,
                F_UNET_KLEIN, F_CLIP_KLEIN, F_VAE_KLEIN]

    def edit_frame(self, client, image, prompt, steps=4, seed=26416064315367, **kw):
        # image may be a filename string or an Asset reference dict
        if isinstance(image, dict):
            img_ref = image
        else:
            img_ref = {"__type": "core/ASSET", "info": {"file_path": image}}
        g = build_frame_edit(img_ref, prompt, seed=seed, steps=steps)
        return _run_graph(client, g, "9")

    def propagate(self, client, video, edited_frame, prompt, frames=121, seed=125348341465200,
                  width=768, height=416, steps=8, strength=1.2, **kw):
        # both video (VHS_LoadVideo) and edited_frame (LoadImage) need core/ASSET refs
        if isinstance(video, dict):
            vid_ref = video
        else:
            vid_ref = {"__type": "core/ASSET", "info": {"file_path": video}}
        if isinstance(edited_frame, dict):
            frame_ref = edited_frame
        else:
            frame_ref = {"__type": "core/ASSET", "info": {"file_path": edited_frame}}
        g = build_ripple(vid_ref, frame_ref, prompt=prompt, frames=frames, seed=seed,
                         width=width, height=height, steps=steps, strength=strength)
        return _run_graph(client, g, "425")


class MiniMaxH3Engine(Engine):
    """Alternative engine — reuses the same pipeline shape with the H3 model
    stack (ref2va / fl2va + motion adapters)."""
    name = "minimax-h3"
    label = "MiniMax H3"
    requires = []

    def edit_frame(self, client, image, prompt, **kw):
        raise NotImplementedError(
            "MiniMax H3 engine: frame editing reuses FLUX.2 Klein "
            "(engine-agnostic step). Call LTXRippleEngine.edit_frame.")

    def propagate(self, client, video, edited_frame, prompt, **kw):
        raise NotImplementedError(
            "MiniMax H3 propagation is not wired yet. The H3 motion-transfer "
            "path (ref2va + motion adapter) is the next engine to implement.")


ENGINES: dict[str, Engine] = {e.name: e for e in (LTXRippleEngine(), MiniMaxH3Engine())}


# --------------------------------------------------------------------------
# comfy-sdk glue
# --------------------------------------------------------------------------
def make_client():
    """Build a Comfy SDK client. COMFY_BASE_URL selects the target."""
    from comfy_sdk import Comfy
    return Comfy()


def _run_graph(client, graph: dict, output_node: str, on_progress: Callable | None = None):
    """Submit a naked API-format graph and return the first output filename."""
    import urllib.request, urllib.error
    data = json.dumps({"workflow": graph}).encode()
    req = urllib.request.Request(
        f"{COMFY_BASE_URL}/api/v2/jobs",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"ComfyUI rejected workflow (HTTP {e.code}): {body[:500]}")
    job_id = resp.get("id")
    if not job_id:
        raise RuntimeError(f"No job id in response: {resp}")
    if on_progress:
        on_progress(f"job {job_id} submitted")
    # Poll for completion
    import time as _time
    deadline = _time.time() + 1800  # 30 min timeout
    while _time.time() < deadline:
        _time.sleep(5)
        try:
            with urllib.request.urlopen(f"{COMFY_BASE_URL}/api/v2/jobs/{job_id}", timeout=10) as r:
                st = json.load(r)
        except Exception:
            continue
        status = st.get("status")
        if on_progress:
            on_progress(f"job {job_id} {status}")
        if status == "succeeded":
            outputs = st.get("outputs", [])
            if not outputs:
                raise RuntimeError(f"no outputs on node {output_node}")
            # Find the output for our node
            for out in outputs:
                if out.get("node_id") == output_node:
                    url = out.get("url")
                    if url:
                        fname = out.get("name", f"output_{output_node}.png")
                        dest = WORK / "media" / fname
                        urllib.request.urlretrieve(url, dest)
                        return fname
            # Fallback: first output
            out = outputs[0]
            url = out.get("url")
            fname = out.get("name", f"output_{output_node}.png")
            dest = WORK / "media" / fname
            urllib.request.urlretrieve(url, dest)
            return fname
        elif status == "failed":
            raise RuntimeError(f"Job {job_id} failed: {st}")
    raise RuntimeError(f"Job {job_id} timed out after 30 min")


def _graph_to_workflow(client, graph: dict):
    """Fallback: write the graph to a temp file and load it as a workflow."""
    tmp = WORK / "media" / f"_graph_{uuid.uuid4().hex}.json"
    tmp.write_text(json.dumps(graph))
    return client.workflows.from_file(str(tmp))


# --------------------------------------------------------------------------
# media helpers
# --------------------------------------------------------------------------
def ffprobe(path: str | Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,nb_frames,r_frame_rate,duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    fr = s.get("r_frame_rate", "24/1")
    num, _, den = fr.partition("/")
    fps = float(num) / float(den or 1)
    return {"width": int(s["width"]), "height": int(s["height"]),
            "fps": fps, "frames": int(s.get("nb_frames") or 0),
            "duration": float(s.get("duration") or 0)}


def extract_first_frame(video: Path, dest: Path) -> Path:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video),
                    "-vf", "select=eq(n\\,0)", "-vframes", "1", str(dest)],
                   check=True)
    return dest



def extract_segment_frames(video: str | Path, segments: list[dict],
                          output_dir: Path | None = None) -> list[Path]:
    """Extract the first frame from each detected segment.

    Args:
        video: Path to input video
        segments: List of {"start": int, "end": int} from detect_scenes()
        output_dir: Where to save frames (default: WORK/media)

    Returns:
        List of paths to extracted frame images
    """
    video = str(video)
    if output_dir is None:
        output_dir = WORK / "media"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    frames = []
    for i, seg in enumerate(segments):
        start_frame = seg["start"]
        dest = output_dir / f"seg_{i:03d}_f{start_frame:04d}.png"
        # Use ffmpeg to extract specific frame
        select_filter = f"select=eq(n,{start_frame})".replace(",", "\\,")
        subprocess.run(
            ["ffmpeg", "-y", "-i", video, "-vf", select_filter,
             "-vframes", "1", str(dest)],
            capture_output=True, check=True
        )
        frames.append(dest)

    return frames



def merge_segments(segment_paths: list[str | Path], output_path: Path | None = None) -> str | None:
    """Merge multiple segment videos into one using ffmpeg concat demuxer.

    Args:
        segment_paths: List of paths to segment video files
        output_path: Where to save merged video (default: WORK/media/merged_<timestamp>.mp4)

    Returns:
        Path to merged video file, or None if input list is empty
    """
    if not segment_paths:
        return None
    if len(segment_paths) == 1:
        return str(segment_paths[0])

    if output_path is None:
        output_path = WORK / "media" / f"merged_{int(time.time())}.mp4"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Create concat list file
    list_file = output_path.parent / f"concat_{int(time.time())}.txt"
    with open(list_file, "w") as f:
        for seg in segment_paths:
            # Escape single quotes in path for ffmpeg concat
            escaped = str(seg).replace("'", "'\''")
            f.write(f"file '{escaped}'\n")

    # Run ffmpeg concat
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
         "-c", "copy", str(output_path)],
        capture_output=True, check=True
    )

    # Clean up list file
    list_file.unlink(missing_ok=True)

    return str(output_path)



def edit_segment(video_path: str | Path, segment: dict, prompt: str,
                client=None, engine=None, **opts) -> str:
    """Edit a single video segment: extract first frame → edit → propagate.

    Args:
        video_path: Path to source video
        segment: {"start": int, "end": int} frame range
        prompt: Edit prompt (e.g. "Replace riders with knights")
        client: ComfySDK client (created if None)
        engine: Engine instance (default: LTXRippleEngine)
        **opts: Additional options for edit_frame/propagate

    Returns:
        Path to edited segment video file
    """
    start, end = segment["start"], segment["end"]
    if start >= end:
        raise ValueError(f"Invalid segment: start ({start}) >= end ({end})")

    if client is None:
        client = make_client()
    if engine is None:
        engine = ENGINES.get("ltx25-ripple")

    # 1. Extract first frame of this segment
    tmp_frame = WORK / "media" / f"seg_f{start:04d}.png"
    select_filter = f"select=eq(n,{start})".replace(",", "\\,")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video_path),
         "-vf", select_filter, "-vframes", "1", str(tmp_frame)],
        capture_output=True, check=True
    )

    # 2. Edit the frame
    asset = client.assets.from_file(str(tmp_frame))
    edited = engine.edit_frame(client, asset.as_reference(), prompt,
                              **opts.get("edit", {}))

    # 3. Propagate to full segment
    # Extract segment video first
    seg_video = WORK / "media" / f"seg_{start:04d}_{end:04d}.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video_path),
         "-vf", f"select='between(n,{start},{end})',setpts=PTS-STARTPTS",
         "-vsync", "vfr", str(seg_video)],
        capture_output=True, check=True
    )

    vasset = client.assets.from_file(str(seg_video))
    edited_asset = client.assets.from_file(str(WORK / "media" / edited))
    result = engine.propagate(client, vasset.file_path,
                              edited_asset.as_reference(),
                              opts.get("ripple_prompt", RIPPLE_PROMPT),
                              **opts.get("propagate", {}))

    return result


def has_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


# --------------------------------------------------------------------------
# jobs
# --------------------------------------------------------------------------
@dataclass
class Job:
    id: str
    status: str = "queued"          # queued | running | done | error
    step: str = ""
    progress: float = 0.0
    engine: str = "ltx25-ripple"
    prompt: str = ""
    video: str = ""
    result: str | None = None
    error: str | None = None
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def path(self) -> Path:
        return WORK / "jobs" / f"{self.id}.json"

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(self), indent=1))

    @staticmethod
    def load(job_id: str) -> "Job":
        p = WORK / "jobs" / f"{job_id}.json"
        if not p.exists():
            raise KeyError(job_id)
        return Job(**json.loads(p.read_text()))

    @staticmethod
    def all() -> list["Job"]:
        js = []
        for p in sorted((WORK / "jobs").glob("*.json"), reverse=True):
            try:
                js.append(Job(**json.loads(p.read_text())))
            except Exception:
                continue
        return js


def run_pipeline(job: Job, video_path: Path, opts: dict) -> None:
    """Multi-segment pipeline: detect cuts → edit each segment → merge.
    Runs in a worker thread."""
    engine = ENGINES.get(job.engine)
    if engine is None:
        job.status, job.error = "error", f"unknown engine {job.engine}"
        job.save()
        return

    job.status, job.started, job.step = "running", time.time(), "init"
    job.save()

    try:
        # 1. detect scene cuts (no client needed)
        job.step, job.progress = "detect_scenes", 0.02
        job.save()
        segments = detect_scenes(video_path)
        if not segments:
            job.status, job.error = "error", "no scenes detected"
            job.save()
            return

        # 2. create client
        client = make_client()

        # 3. edit each segment
        edited_segments = []
        total = len(segments)
        for i, seg in enumerate(segments):
            job.step = f"edit_segment_{i + 1}/{total}"
            job.progress = 0.05 + (0.9 * i / total)
            job.save()
            # Remove 'prompt' from opts to avoid duplicate argument
            seg_opts = {k: v for k, v in opts.items() if k != "prompt"}
            result = edit_segment(
                video_path=video_path,
                segment=seg,
                prompt=job.prompt,
                client=client,
                engine=engine,
                **seg_opts
            )
            edited_segments.append(result)

        # 4. merge segments
        job.step, job.progress = "merge_segments", 0.95
        job.save()
        if len(edited_segments) == 1:
            result = edited_segments[0]
        else:
            result = merge_segments(edited_segments)

        # 5. upscale (optional)
        if opts.get("upscale", False):
            job.step, job.progress = "upscale", 0.98
            job.save()
            result = upscale_video(result, scale=opts.get("upscale_scale", 2.0))

        job.result, job.status, job.step, job.progress = result, "done", "done", 1.0
    except Exception as e:  # noqa: BLE001 - surface any engine failure to the UI
        job.status, job.error = "error", f"{type(e).__name__}: {e}"
        job.save()

def upscale_video(input_path: str | Path, output_path: str | Path | None = None,
                  scale: float = 2.0) -> str:
    """Upscale video resolution using ffmpeg scale filter.

    Args:
        input_path: Path to input video
        output_path: Where to save upscaled video (default: WORK/media/upscaled_<timestamp>.mp4)
        scale: Upscale factor (2.0 = double resolution)

    Returns:
        Path to upscaled video file
    """
    input_path = str(input_path)
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input video not found: {input_path}")
    if output_path is None:
        output_path = WORK / "media" / f"upscaled_{int(time.time())}.mp4"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Get input dimensions
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", input_path],
        capture_output=True, text=True, check=True
    )
    info = json.loads(probe.stdout)
    stream = info["streams"][0]
    width = int(stream["width"])
    height = int(stream["height"])

    new_width = int(width * scale)
    new_height = int(height * scale)

    # Use ffmpeg scale filter with lanczos for quality
    subprocess.run(
        ["ffmpeg", "-y", "-i", input_path,
         "-vf", f"scale={new_width}:{new_height}:flags=lanczos",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-c:a", "copy", str(output_path)],
        capture_output=True, check=True
    )

    return str(output_path)

