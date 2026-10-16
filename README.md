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
| GPU | 24 GB VRAM recommended; a real two-shot app run completed on RTX 3090 (see validation limits below) |
| Python | 3.12 (setup creates a project-local `.venv` with `uv`) |
| FFmpeg | `ffmpeg` and `ffprobe` available on `PATH` |
| Local SDK proxy | `comfy-api-proxy` 0.1.6, installed only with `--with-proxy`; bridges the SDK v2 API to self-hosted ComfyUI |

The frame editor also requires FLUX.2 Klein 9B and its ComfyUI-compatible text encoder/VAE installed locally. Model downloads are user-managed and must follow each model's terms.


---

## Install

```bash
# Install uv and FFmpeg first: see docs/local-setup.md
git clone https://github.com/lvsas/Open-Source-Higgsfield-Competition.git
cd Open-Source-Higgsfield-Competition
bash scripts/setup.sh --with-proxy
```

`bash scripts/setup.sh` installs only the app dependencies. The separate
`--with-proxy` flag explicitly opts into installing the local proxy; setup never
starts services, installs ComfyUI/custom nodes, or downloads model weights.

Start your prepared ComfyUI instance, then run the proxy in one terminal:

```bash
# Upstream ComfyUI; override this for a trusted remote server.
export COMFYUI_URL=http://127.0.0.1:8188
env -u PYTHONPATH .venv/bin/comfy-api-proxy run \
  --comfyui "$COMFYUI_URL" --host 127.0.0.1 --port 8189
```

In a second terminal, from the repository root:

```bash
# SDK target is the proxy, not the raw ComfyUI port.
COMFY_BASE_URL=http://127.0.0.1:8189 bash scripts/run_app.sh
```

Open `http://127.0.0.1:8000`. Both services bind to loopback only. The launcher
requires Python 3.12 and clears inherited `PYTHONPATH`. See the
[local setup guide](docs/local-setup.md) for remote upstreams, readiness checks,
safe environment recovery, and the limits of a successful install.


---

## Models

`env -u PYTHONPATH .venv/bin/python scripts/download_models.py --comfyui /path/to/ComfyUI` downloads the public LTX 2.5 + Ripple components into their ComfyUI folders; use `--dry-run` to inspect the targets first. Run this where the ComfyUI model directories are accessible; a remote HTTP endpoint alone is not a model installation path. The script does not bundle weights in this repository.

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
# Keep the proxy running in its own terminal (see Install).
COMFY_BASE_URL=http://127.0.0.1:8189 bash scripts/run_app.sh
```

Then open `http://127.0.0.1:8000`, choose a source video, optionally add a character reference, identify the visible target when useful, describe the transformation, and launch the job. The Creative Studio previews selected local media, keeps the job ID across reloads, translates pipeline progress into user-facing stages, and exposes a result MP4 when ComfyUI finishes. Studio HD is the current public path: a 1280px long edge and 16 Ripple inference steps. Ripple strength remains an advanced control; 1.2 is a starting point, not a universal optimum.

Check `GET /api/readiness` before submitting a job. `GET /health` proves only that
the app process is alive; it does not validate the proxy, upstream, nodes or models.

The CLI in `src/genjutsu.py` is a legacy LTX 2.3 prototype and is not the current app entry point.

---

## Documentation

- [Local setup and troubleshooting](docs/local-setup.md) — Python 3.12, FFmpeg, opt-in proxy, remote upstream and readiness
- [Creative Studio UI architecture](docs/ui-architecture.md) — product workflow, engine visual identity and honest local-sharing boundary
- [Competition UX/viral-readiness audit](docs/audits/2026-10-16-competition-ux-gap.md) — verified gap analysis and follow-up gates
- [`src/app.py`](src/app.py) — local UI, upload endpoint, job tracking and result route
- [`src/core.py`](src/core.py) — job persistence and pipeline orchestration
- [`src/graphs.py`](src/graphs.py) — FLUX.2 Klein and LTX/Ripple API-format graphs
- [`src/comfy_transport.py`](src/comfy_transport.py) — official SDK target, execution and downloads
- [`src/segments.py`](src/segments.py) — per-shot asset transfer, padding and exact frame restoration
- [`scripts/download_models.py`](scripts/download_models.py) — idempotent LTX/Ripple weight setup
- [ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo)
- [ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite)
- [ComfyUI-KJNodes](https://github.com/kijai/ComfyUI-KJNodes)


---

## Character Reference Status

The Creative Studio accepts an optional PNG/JPEG/WebP character reference in the main job form. It is stored with the job, transferred as a Comfy asset for each shot, and injected into the FLUX frame-edit conditioning path. Unit and HTTP-contract tests cover this route.

This is not proof of visual identity consistency across every real video. In particular, a reference image does not solve an absent or occluded target; that requires a separately validated anchoring/tracking strategy.

## Upscale

The pipeline supports optional spatial upscaling (default 2x) via `upscale_video()`. Enable with `upscale: True` in job options. Uses ffmpeg lanczos scaling for quality.

## Architecture

```
src/
  app.py              — FastAPI upload, job and result routes
  core.py             — Comfy SDK pipeline (detect → edit → merge → upscale)
  static/
    design-system.css — engine-scoped visual tokens and reusable UI primitives
    app.css            — responsive Creative Studio layout
    app.js             — previews, job states, local export actions
  templates/index.html — English-first Creative Studio UI
  genjutsu.py     — Legacy LTX 2.3 CLI prototype (not current entry point)
tests/            — Unit and regression tests (unittest)
scripts/
  download_models.py — Idempotent LTX/Ripple weight setup
```

**Pipeline**: `detect_scenes()` → `edit_segment()` per shot → `merge_segments()` → `upscale_video()`

**Cloud support is not yet verified.** The current local workflow targets a Comfy API endpoint; do not assume `COMFY_API_KEY` alone enables Cloud until authentication, asset transfer, model availability, submission, and output download have been tested against the official Cloud API.

## Current Evidence

- A real two-shot run was submitted through the web form, processed by FLUX.2 Klein and LTX/Ripple, downloaded, and played through to the end in Chromium: 121 frames, 24 fps, 768×416. Shot padding is removed before assembly; the app restores source audio when present.
- **Visual quality is not validated:** the corrected run preserves the scene cut, but recolors/armors the tiger despite instructions to preserve it. Successful execution is not a successful selective edit or a contest-ready result.
- CPU tests are self-contained; they do not require the private development clip. They do not prove GPU quality, reference-image behavior on real footage, Cloud compatibility or licensing eligibility.
- The Creative Studio UI is implemented and browser-checked for desktop/mobile layout, source preview and HTTP/API integration. Local Download and Copy caption are real actions; **public social sharing is not implemented** because no hosted, recipient-accessible result URL exists.
- MiniMax H3 appears only as a disabled visual extension point. Its generation backend, Cloud and a real-GPU character-reference run remain unverified end to end.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Write tests first (TDD)
4. Run `env -u PYTHONPATH .venv/bin/python -m unittest discover -s tests -v`
5. Commit with descriptive messages
6. Open a PR

## License

Apache-2.0 — see [LICENSE](LICENSE).

This repository is Apache-2.0. LTX 2.5, Ripple, FLUX.2 Klein and all ComfyUI extensions retain their own licenses and acceptable-use terms; review those terms separately before commercial use or redistribution.
