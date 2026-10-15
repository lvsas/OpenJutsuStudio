# OpenGenjutsu — Open-Source Reality Manipulation for Video

**An open-source rebuild of [Higgsfield Genjutsu](https://higgsfield.ai/genjutsu) on the [Comfy Developer Platform](https://comfy.org/platform).**

Genjutsu is a paid feature that transforms footage you already shot — no reshoot.
This project rebuilds it in the open, on top of open-weight models.

Built for the **Open Source Higgsfield Competition** (ComfyUI · NVIDIA · Runpod).

---

## What it does

## Current MVP: Object Swap with LTX 2.5 + Ripple

The first working product path is a local-first **video object/attribute edit**:

```
source video + edit instruction
        → edit frame 0 with FLUX.2 Klein image editing
        → propagate with LTX 2.5 + Ripple FFAF IC-LoRA
        → previewable edited video
```

The target is the observable Genjutsu workflow, not a claim to reproduce Higgsfield's undisclosed internals. The current app implements this Object Swap path; **Motion Transfer is not implemented yet** and is not advertised as a working feature. A later milestone can add reference-driven Motion Transfer after this pipeline is reliable.


---

## Why LTX 2.5 + Ripple

LTX 2.5 + Ripple is an open-weight **First Frame All Frames (FFAF)** workflow: an image editor changes the first frame, then the Ripple IC-LoRA propagates the change through the source video's motion. This gives us an actionable control point and a fast local video stage. It is our documented implementation choice, not a statement about Genjutsu's private pipeline.

The LTX 2.5 components and Ripple adapter have separate model licenses/terms. Review them before redistribution or commercial use; this repository does not bundle model weights.


---

## Requirements

| | |
|---|---|
| ComfyUI | ≥ 0.40, with the LTXVideo, VideoHelperSuite and KJNodes packs used by the workflow |
| Comfy SDK | `comfy-sdk` 0.5.x |
| GPU | 24 GB VRAM recommended; tested on RTX 3090, but the full edit path still needs a clean end-to-end verification |
| Python | ≥ 3.10 |

The frame editor also requires FLUX.2 Klein 9B and its ComfyUI-compatible text encoder/VAE installed locally. Model downloads are user-managed and must follow each model's terms.


---

## Install

```bash
git clone https://github.com/<you>/opengenjutsu
cd opengenjutsu
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Start local ComfyUI or Comfy API proxy first, then point the SDK at it:
export COMFY_BASE_URL="http://127.0.0.1:8189"
uvicorn app:app --app-dir src --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. The app uploads a video, validates its stream with `ffprobe`, runs the first-frame editor and Ripple propagation as one tracked job, and serves the resulting MP4. GPU inference is delegated to ComfyUI via the Comfy SDK.


---

## Models

`python scripts/download_models.py --comfyui /path/to/ComfyUI` downloads the public LTX 2.5 + Ripple components into their ComfyUI folders; use `--dry-run` to inspect the targets first. The script does not bundle weights in this repository.

| File | Folder | Role |
|---|---|---|
| `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` | `diffusion_models` | LTX 2.5 video model |
| `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` | `text_encoders` | LTX text encoder |
| `ltx-2.5-video-vae-conv-bf16.safetensors` | `vae` | video VAE |
| `ltx-2.5-audio-vae-bf16.safetensors` | `vae` | audio VAE |
| `LTX25_Ripple_v11.safetensors` | `loras` | FFAF propagation adapter |

The image-edit stage additionally requires the ComfyUI-compatible FLUX.2 Klein 9B checkpoint, text encoder, and VAE named in `src/core.py`. Those editor files are not auto-downloaded by this script yet; install them through the relevant official/ComfyUI model source and review their license terms. The gated LTX in/outpainting IC-LoRA is **not** required by this Ripple-based MVP.


---

## Run the app

```bash
COMFY_BASE_URL="http://127.0.0.1:8189" uvicorn app:app --app-dir src --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000`, select a video, describe the first-frame edit, and launch the job. The UI keeps the job ID across reloads, shows its phase, and exposes the MP4 when ComfyUI finishes. The default Ripple strength is 1.2 as a conservative starting point; it is a user-adjustable control, not a universally validated optimum.

The CLI in `src/genjutsu.py` is a legacy LTX 2.3 prototype and is not the current app entry point.

---

## Documentation

- [`src/app.py`](src/app.py) — local UI, upload endpoint, job tracking and result route
- [`src/core.py`](src/core.py) — Comfy SDK graph builders and the LTX 2.5 + Ripple pipeline
- [`scripts/download_models.py`](scripts/download_models.py) — idempotent LTX/Ripple weight setup
- [ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo)
- [ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite)
- [ComfyUI-KJNodes](https://github.com/kijai/ComfyUI-KJNodes)


---

## License

Apache-2.0 — see [LICENSE](LICENSE).

This repository is Apache-2.0. LTX 2.5, Ripple, FLUX.2 Klein and all ComfyUI extensions retain their own licenses and acceptable-use terms; review those terms separately before commercial use or redistribution.
