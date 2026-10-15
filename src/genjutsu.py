#!/usr/bin/env python3
"""
OpenGenjutsu — open-source reality manipulation for video.

Rebuild of Higgsfield Genjutsu on the Comfy Developer Platform.

Modes:
  swap      Object Swap   — replace/erase an element, keep the rest intact
  transfer  Motion Transfer — keep motion/camera, rebuild cast/location/look

Uses the Comfy SDK (`pip install comfy-sdk`), which runs against a local
ComfyUI, a Comfy API deployment, or Comfy Cloud — only COMFY_BASE_URL changes.

Examples:
  # Object swap, explicit mask
  python genjutsu.py swap --video in.mp4 --mask wm.png \\
      --prompt "remove the text overlay" --out result.mp4

  # Object swap, auto-mask via SAM3 (needs --segment)
  python genjutsu.py swap --video in.mp4 --segment "the crystal glass" \\
      --prompt "remove the crystal glass" --out result.mp4

  # Motion transfer from a reference image
  python genjutsu.py transfer --video in.mp4 --reference style.png \\
      --prompt "the character walks through a neon-lit market" --out result.mp4
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

DEFAULT_BASE = os.environ.get("COMFY_BASE_URL", "http://127.0.0.1:8188")

# --- model files (see README > Models) ---
UNET = "ltx-2.3-22b-dev_transformer_only_fp8_scaled.safetensors"
VAE_VID = "LTX23_video_vae_bf16.safetensors"
VAE_AUD = "LTX23_audio_vae_bf16.safetensors"
CLIP1 = "gemma_3_12B_it_fp4_mixed.safetensors"
CLIP2 = "ltx-2.3_text_projection_bf16.safetensors"
LORA_DIST = "ltx-2.3-22b-distilled-lora-384-1.1.safetensors"
LORA_OBSC = "LTX23_Obscura_Remova_v1.safetensors"
LORA_UNION = "ltx-2.3-22b-ic-lora-union-control-ref0.5.safetensors"

NEG = ("blurry, low resolution, ugly, garbled mess, compression artifacts, "
       "glitch, stop motion, still image, pixelated, robotic voice, oversaturated")


# --------------------------------------------------------------------------
# graph building
# --------------------------------------------------------------------------
def _loaders(wf):
    wf["1"] = {"class_type": "VAELoaderKJ",
               "inputs": {"vae_name": VAE_VID, "device": "main_device", "weight_dtype": "bf16"}}
    wf["2"] = {"class_type": "VAELoaderKJ",
               "inputs": {"vae_name": VAE_AUD, "device": "main_device", "weight_dtype": "bf16"}}
    wf["4"] = {"class_type": "DualCLIPLoader",
               "inputs": {"clip_name1": CLIP1, "clip_name2": CLIP2, "type": "ltxv",
                          "device": "default"}}
    wf["5"] = {"class_type": "UNETLoader",
               "inputs": {"unet_name": UNET, "weight_dtype": "default"}}
    wf["9"] = {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["4", 0]}}
    wf["22"] = {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["4", 0]}}
    return wf


def _video_input(wf, video, frames, fps, w, h):
    wf["791"] = {"class_type": "VHS_LoadVideo",
                 "inputs": {"video": video, "force_rate": float(fps), "custom_width": 0,
                            "custom_height": 0, "frame_load_cap": frames,
                            "skip_first_frames": 0, "select_every_nth": 1, "format": "LTXV"}}
    wf["782"] = {"class_type": "ImageResizeKJv2",
                 "inputs": {"image": ["791", 0], "width": w, "height": h,
                            "upscale_method": "lanczos", "keep_proportion": "crop",
                            "pad_color": "0, 0, 0", "crop_position": "center",
                            "divisible_by": 2, "device": "cpu"}}
    wf["775"] = {"class_type": "Frame Select", "inputs": {"frames": ["782", 0], "select": 0}}
    wf["776"] = {"class_type": "GetImageSize", "inputs": {"image": ["775", 0]}}
    wf["560"] = {"class_type": "VHS_GetImageCount", "inputs": {"images": ["782", 0]}}
    wf["567"] = {"class_type": "EmptyLTXVLatentVideo",
                 "inputs": {"width": ["776", 0], "height": ["776", 1],
                            "length": ["560", 0], "batch_size": 1}}
    wf["562"] = {"class_type": "LTXVEmptyLatentAudio",
                 "inputs": {"frames_number": ["560", 0], "frame_rate": float(fps),
                            "batch_size": 1, "audio_vae": ["2", 0]}}
    wf["563"] = {"class_type": "LTXVConditioning",
                 "inputs": {"positive": ["9", 0], "negative": ["22", 0], "frame_rate": float(fps)}}
    return wf


def _lora_chain(wf, obscura_strength, dist_strength, use_obscura=True):
    base = ["5", 0]
    if use_obscura:
        wf["15"] = {"class_type": "LoraLoaderModelOnly",
                    "inputs": {"model": ["5", 0], "lora_name": LORA_OBSC,
                               "strength_model": obscura_strength}}
        base = ["15", 0]
    wf["14"] = {"class_type": "LoraLoaderModelOnly",
                "inputs": {"model": base, "lora_name": LORA_DIST,
                           "strength_model": dist_strength}}
    return wf


def _tail(wf, guide_node, fps, steps, seed, cfg, prefix):
    """Assemble A/V, sample, decode, save."""
    wf["401"] = {"class_type": "LTXVConcatAVLatent",
                 "inputs": {"video_latent": [guide_node, 2], "audio_latent": ["562", 0]}}
    wf["19"] = {"class_type": "KSampler",
                "inputs": {"model": ["14", 0], "seed": seed, "steps": steps, "cfg": cfg,
                           "sampler_name": "euler_ancestral_cfg_pp",
                           "scheduler": "linear_quadratic", "denoise": 1.0,
                           "positive": [guide_node, 0], "negative": [guide_node, 1],
                           "latent_image": ["401", 0]}}
    wf["423"] = {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["19", 0]}}
    wf["445"] = {"class_type": "VAEDecode", "inputs": {"samples": ["423", 0], "vae": ["1", 0]}}
    wf["504"] = {"class_type": "LTXVAudioVAEDecode",
                 "inputs": {"samples": ["423", 1], "audio_vae": ["2", 0]}}
    wf["425"] = {"class_type": "VHS_VideoCombine",
                 "inputs": {"images": ["445", 0], "audio": ["504", 0],
                            "frame_rate": float(fps), "loop_count": 0,
                            "filename_prefix": prefix, "format": "video/h264-mp4",
                            "pingpong": False, "save_output": True}}
    return wf


def build_swap(video, prompt, mask=None, frames=121, seed=132464, fps=24,
               w=1280, h=704, obscura_strength=1.25, dist_strength=0.4,
               steps=8, cfg=1.0, guide_strength=1.0, denoise_strength=1.0,
               attention_strength=1.0, mask_mode="both", invert_mask=False,
               use_obscura=True):
    """Object Swap. With a mask -> targeted edit (FL_LTXVMaskedICLoRAGuide).
    Without a mask -> whole-frame edit (LTXAddVideoICLoRAGuide)."""
    wf = _loaders({})
    wf["9"]["inputs"]["text"] = prompt
    wf = _video_input(wf, video, frames, fps, w, h)
    wf = _lora_chain(wf, obscura_strength, dist_strength, use_obscura)

    if mask:
        wf["800"] = {"class_type": "LoadImage", "inputs": {"image": mask}}
        wf["801"] = {"class_type": "ImageToMask",
                     "inputs": {"image": ["800", 0], "channel": "red"}}
        wf["570"] = {"class_type": "FL_LTXVMaskedICLoRAGuide",
                     "inputs": {"positive": ["563", 0], "negative": ["563", 1],
                                "vae": ["1", 0], "latent": ["567", 0],
                                "image": ["782", 0], "mask": ["801", 0],
                                "frame_idx": 0, "guide_strength": guide_strength,
                                "denoise_strength": denoise_strength,
                                "attention_strength": attention_strength,
                                "mask_mode": mask_mode, "invert_mask": invert_mask,
                                "inpaint_preprocess": True, "write_source_to_latent": True,
                                "latent_downscale_factor": 1.0, "crop": "disabled",
                                "use_tiled_encode": False, "tile_size": 256,
                                "tile_overlap": 64}}
    else:
        wf["570"] = {"class_type": "LTXAddVideoICLoRAGuide",
                     "inputs": {"positive": ["563", 0], "negative": ["563", 1],
                                "vae": ["1", 0], "latent": ["567", 0],
                                "image": ["782", 0], "frame_idx": 0,
                                "strength": guide_strength,
                                "latent_downscale_factor": 1.0, "crop": "disabled",
                                "use_tiled_encode": False, "tile_size": 256,
                                "tile_overlap": 64}}
    return _tail(wf, "570", fps, steps, seed, cfg, "objectswap")


def build_transfer(video, reference, prompt, frames=121, seed=132464, fps=24,
                   w=1280, h=704, dist_strength=0.4, steps=8, cfg=1.0,
                   guide_strength=1.0):
    """Motion Transfer: the source video drives motion/camera; the reference
    image supplies the new look. Uses the Union-Control IC-LoRA."""
    wf = _loaders({})
    wf["9"]["inputs"]["text"] = prompt
    wf = _video_input(wf, video, frames, fps, w, h)

    # Union-Control IC-LoRA on the model
    wf["16"] = {"class_type": "LoraLoaderModelOnly",
                "inputs": {"model": ["5", 0], "lora_name": LORA_UNION,
                           "strength_model": 1.0}}
    wf["14"] = {"class_type": "LoraLoaderModelOnly",
                "inputs": {"model": ["16", 0], "lora_name": LORA_DIST,
                           "strength_model": dist_strength}}

    # reference image feeds the latent as the first frame
    wf["810"] = {"class_type": "LoadImage", "inputs": {"image": reference}}
    wf["811"] = {"class_type": "ImageResizeKJv2",
                 "inputs": {"image": ["810", 0], "width": w, "height": h,
                            "upscale_method": "lanczos", "keep_proportion": "crop",
                            "pad_color": "0, 0, 0", "crop_position": "center",
                            "divisible_by": 2, "device": "cpu"}}
    wf["570"] = {"class_type": "LTXAddVideoICLoRAGuide",
                 "inputs": {"positive": ["563", 0], "negative": ["563", 1],
                            "vae": ["1", 0], "latent": ["567", 0],
                            "image": ["811", 0], "frame_idx": 0,
                            "strength": guide_strength,
                            "latent_downscale_factor": 1.0, "crop": "disabled",
                            "use_tiled_encode": False, "tile_size": 256,
                            "tile_overlap": 64}}
    return _tail(wf, "570", fps, steps, seed, cfg, "motiontransfer")


# --------------------------------------------------------------------------
# ComfyUI client
# --------------------------------------------------------------------------
def upload(base, path, subfolder=""):
    """Upload a file to ComfyUI's input dir. Returns the stored filename."""
    import mimetypes
    boundary = "----og" + uuid.uuid4().hex
    name = os.path.basename(path)
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    with open(path, "rb") as f:
        data = f.read()
    parts = []
    for field, value in (("type", "input"), ("subfolder", subfolder), ("overwrite", "true")):
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"\r\n\r\n"
                     f"{value}\r\n".encode())
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; "
                 f"filename=\"{name}\"\r\nContent-Type: {ctype}\r\n\r\n".encode())
    parts.append(data)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(f"{base}/upload/image", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    r = json.load(urllib.request.urlopen(req, timeout=300))
    return r.get("name", name)


def submit(base, wf):
    body = json.dumps({"prompt": wf, "client_id": str(uuid.uuid4())}).encode()
    req = urllib.request.Request(f"{base}/prompt", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=120))
    except urllib.error.HTTPError as e:
        detail = e.read().decode()
        print(f"ComfyUI rejected the workflow (HTTP {e.code}):\n{detail[:3000]}",
              file=sys.stderr)
        sys.exit(1)
    if r.get("node_errors"):
        print("Node errors:", json.dumps(r["node_errors"], indent=1)[:3000], file=sys.stderr)
        sys.exit(1)
    return r["prompt_id"]


def wait(base, pid, poll=5, quiet=False):
    """Poll history until the prompt finishes. Returns the output filenames."""
    t0 = time.time()
    while True:
        with urllib.request.urlopen(f"{base}/history/{pid}", timeout=60) as r:
            h = json.load(r)
        if h:
            entry = h[pid]
            st = entry.get("status", {})
            if st.get("status_str") == "error":
                for m in st.get("messages", []):
                    if m[0] == "execution_error":
                        print(f"Execution error: {json.dumps(m[1])[:1500]}", file=sys.stderr)
                sys.exit(1)
            if st.get("completed"):
                files = []
                for out in entry.get("outputs", {}).values():
                    for key in ("gifs", "images", "videos"):
                        for item in out.get(key, []):
                            if isinstance(item, dict) and item.get("filename"):
                                files.append(item["filename"])
                return files, time.time() - t0
        if not quiet:
            print(f"\r  running… {int(time.time()-t0)}s", end="", flush=True)
        time.sleep(poll)


def download(base, filename, dest):
    url = f"{base}/view?filename={urllib.parse.quote(filename)}&subfolder=&type=output"
    urllib.request.urlretrieve(url, dest)
    return dest


# --------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description="OpenGenjutsu — open-source Genjutsu rebuild")
    p.add_argument("--base", default=DEFAULT_BASE, help="ComfyUI base URL")
    sub = p.add_subparsers(dest="mode", required=True)

    for name in ("swap", "transfer"):
        s = sub.add_parser(name)
        s.add_argument("--video", required=True)
        s.add_argument("--prompt", required=True)
        s.add_argument("--out", default="result.mp4")
        s.add_argument("--frames", type=int, default=121)
        s.add_argument("--seed", type=int, default=132464)
        s.add_argument("--fps", type=int, default=24)
        s.add_argument("--width", type=int, default=1280)
        s.add_argument("--height", type=int, default=704)
        s.add_argument("--steps", type=int, default=8)
        s.add_argument("--cfg", type=float, default=1.0)
        s.add_argument("--guide", type=float, default=1.0)
        s.add_argument("--workflow-out", help="écrit le workflow API et sort")
        if name == "swap":
            s.add_argument("--mask", help="PNG masque (blanc = zone à éditer)")
            s.add_argument("--obscura", type=float, default=1.25)
            s.add_argument("--denoise", type=float, default=1.0)
            s.add_argument("--attention", type=float, default=1.0)
            s.add_argument("--mask-mode", default="both",
                           choices=["both", "latent_noise", "attention"])
            s.add_argument("--invert-mask", action="store_true")
            s.add_argument("--no-obscura", action="store_true")
        else:
            s.add_argument("--reference", required=True, help="image de référence")

    a = p.parse_args()
    base = a.base.rstrip("/")

    if a.mode == "swap":
        wf = build_swap(a.video, a.prompt, mask=a.mask, frames=a.frames, seed=a.seed,
                        fps=a.fps, w=a.width, h=a.height, obscura_strength=a.obscura,
                        steps=a.steps, cfg=a.cfg, guide_strength=a.guide,
                        denoise_strength=a.denoise, attention_strength=a.attention,
                        mask_mode=a.mask_mode, invert_mask=a.invert_mask,
                        use_obscura=not a.no_obscura)
    else:
        wf = build_transfer(a.video, a.reference, a.prompt, frames=a.frames, seed=a.seed,
                            fps=a.fps, w=a.width, h=a.height, steps=a.steps,
                            cfg=a.cfg, guide_strength=a.guide)

    if a.workflow_out:
        with open(a.workflow_out, "w") as f:
            json.dump({"prompt": wf}, f, indent=1)
        print(f"workflow écrit -> {a.workflow_out}")
        return

    # upload inputs
    vid = upload(base, a.video)
    wf["791"]["inputs"]["video"] = vid
    if a.mode == "swap" and a.mask:
        wf["800"]["inputs"]["image"] = upload(base, a.mask)
    if a.mode == "transfer":
        wf["810"]["inputs"]["image"] = upload(base, a.reference)

    print(f"[{a.mode}] submitting to {base} …")
    pid = submit(base, wf)
    print(f"  prompt_id: {pid}")
    files, elapsed = wait(base, pid)
    print(f"\n  done in {elapsed:.0f}s")
    if not files:
        print("  no output files reported", file=sys.stderr)
        sys.exit(1)
    download(base, files[-1], a.out)
    print(f"  -> {a.out}")


if __name__ == "__main__":
    main()
