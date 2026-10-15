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
# Requires uv: https://docs.astral.sh/uv/
git clone https://github.com/<you>/opengenjutsu
cd opengenjutsu
bash scripts/setup.sh
bash scripts/run_app.sh
```

Open `http://127.0.0.1:8000`. The launcher binds to loopback only and clears an inherited `PYTHONPATH` so packages from another Python environment cannot break the app import.


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
bash scripts/run_app.sh
```

Then open `http://127.0.0.1:8000`, select a video, describe the first-frame edit, and launch the job. The UI keeps the job ID across reloads, shows its phase, and exposes the MP4 when ComfyUI finishes. The default Ripple strength is 1.2 as a starting point only; it is not a universally validated optimum.

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

## Character Reference Status

The API has an image-upload endpoint, and the workflow builder has a `reference_image` input. These pieces have **not** yet been connected and verified end-to-end in the web app. The current UI does not offer a character-reference control; do not treat Character Sheet support as a finished user feature.

## Upscale

The pipeline supports optional spatial upscaling (default 2x) via `upscale_video()`. Enable with `upscale: True` in job options. Uses ffmpeg lanczos scaling for quality.

## Architecture

```
src/
  app.py          — FastAPI web UI (upload, job tracking, compare, share)
  core.py         — Comfy SDK pipeline (detect → edit → merge → upscale)
  genjutsu.py     — Legacy LTX 2.3 CLI prototype (not current entry point)
tests/            — Unit tests (35 tests, unittest)
scripts/
  download_models.py — Idempotent LTX/Ripple weight setup
```

**Pipeline**: `detect_scenes()` → `edit_segment()` per shot → `merge_segments()` → `upscale_video()`

**Cloud support is not yet verified.** The current local workflow targets a Comfy API endpoint; do not assume `COMFY_API_KEY` alone enables Cloud until authentication, asset transfer, model availability, submission, and output download have been tested against the official Cloud API.

## Current Evidence

- One local single-shot render was previously produced and inspected; this is not a reproducible test suite or a contest-ready validation result.
- Multi-shot orchestration, reference-image injection, and upscale have unit coverage, but their end-to-end GPU behavior has not been validated as a complete app workflow.
- The current app, Cloud path, and Character Reference UX are prototypes and remain under development.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Write tests first (TDD)
4. Run `python -m unittest discover tests -v`
5. Commit with descriptive messages
6. Open a PR

## License

Apache-2.0 — see [LICENSE](LICENSE).

This repository is Apache-2.0. LTX 2.5, Ripple, FLUX.2 Klein and all ComfyUI extensions retain their own licenses and acceptable-use terms; review those terms separately before commercial use or redistribution.
