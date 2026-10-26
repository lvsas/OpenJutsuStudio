# OpenGenjutsu — Open-Source Reality Manipulation for Video

**An open-source rebuild of [Higgsfield Genjutsu](https://higgsfield.ai/genjutsu) on the [Comfy Developer Platform](https://comfy.org/platform).**

Genjutsu is a paid feature that transforms footage you already shot — no reshoot.
This project rebuilds it in the open, on top of open-weight models.

Built for the **Open Source Higgsfield Competition** (ComfyUI · NVIDIA · Runpod).

**Projects:** the project picker chooses where new attempts are filed; it never adds them to the chosen sequence. Timeline lists both completed Swaps and native takes, with video-only capabilities labeled explicitly. Add/Keep is deliberate. Remove a placement from the sequence, or remove the resource from the project while retaining it in the common library. Used resources must be unplaced first. **Open project → Archive project** hides a named project without deleting its media; **Archived projects → Restore** brings it back. Restore before generating or editing an archive.

**For developers:** start with [Contributing](CONTRIBUTING.md) for setup, GPU-free tests,
module boundaries and review requirements. The [Timeline editor guide](docs/architecture/timeline-editor.md)
describes media editing/export; the separate [H3 artifact integrity contract](docs/architecture/timeline-artifacts.md)
validates native-family files. Neither implies execution-proven native continuation.
The [delivered native recovery slice](docs/validation/native-take-workspace.md) records what the
current Work-in-progress interface actually supports and what remains unavailable.
**Next delivery:** the [feature-complete MVP plan](docs/plans/2026-10-21-mvp-feature-complete.md)
tracks Swap → forward, seed hunting/choice, prepend/bridge, direct creation, refine and engine
capabilities, followed by stabilization, Cloud/SDK validation, UX polish and the two-minute demo.

---

## What it does

You bring footage you already shot and a character reference; the studio returns the same
moment with a different character in it, and a **take capsule** that records exactly what was
consumed so the take can be inspected, exported or re-run.

The studios share a consistent interface, project library and official Comfy SDK transport,
with engine-specific pipelines and receipts—not interchangeable model state:

Both accept up to **15 seconds per Swap** as an application budget, not a VRAM guarantee.
Longer uploads reveal explicit start/end and preview controls; shorter sources stay uncluttered.
The app preserves the original and sends the physically extracted video/audio to the worker.

| Studio | Chain | State |
| --- | --- | --- |
| **LTX Studio** | source + reference(s) → FLUX 2 Klein first-frame edit → LTX 2.5 + Ripple propagation | working |
| **H3 Studio** | source + 1–2 ordered character references → MiniMax H3 two-pass character swap at 0.9 MP | working |

Connected creative workspaces keep the generated content usable beyond one Swap:

| Workspace | What you can do | Boundary |
| --- | --- | --- |
| **Characters — work in progress** (`/characters`) | generate with FLUX 3 Klein, select one canvas, discard recent attempts, explicitly keep a named character in the server library, download/share its PNG and use it in either Swap studio | saving/removing library membership never deletes generation artifacts; navigation never starts a render |
| **Generative Timeline — work in progress** (`/timeline`) | recover a genuine native H3 Take, play its protected preview, inspect/download its public capsule, retain MCTX/COND and lineage, restore the selected Take; assembly/export remains a collapsed supporting tool | native creation, seed candidates and continuation remain experimental, with operation-specific acceptance still open; public capsule JSON alone is not a complete Take backup |

The target Timeline is a **generation-first chronology of continuable Takes**: explore seeds,
choose a candidate, generate after or before it, bridge two boundaries, and recover its frozen
capsule/state. Assembly/export supports that journey rather than becoming a general-purpose editor.
Those native operations are not presented as delivered by the supporting slice above.

The [visible-product evidence](docs/validation/visible-product-slices.md) separates actual browser,
persistence and export checks from unit-test fixtures. A saved Character supplies reference context,
not a generated Timeline clip. The [CPU continuity pack](docs/architecture/continuity-nodes.md)
publishes/re-stages explicit H3 file families and has local H3 runtime evidence; **complete
cross-target portability is not yet accepted**. The [native LTX audit](docs/validation/timeline-ltx-capabilities.md) records
engine-specific candidates and unproven operations rather than claiming H3/LTX state interoperability.

![LTX Studio](docs/readme/ltx-swap.png)

*LTX Studio: the source and the character references are chosen with the same picker both
studios use, and the take capsule records what the render consumed.*

![H3 Studio with two character references and a completed take](docs/readme/h3-swap-two-references.png)

*H3 Studio with two ordered character references and a completed take. The capsule chain
shows one card per reference, and every description the studio wrote is frozen in the take
alongside its provenance — `user` when you typed it, `generated` when the local vision model
read it from your image.*

Type nothing at all and the studio still works: it reads the clip to name what must stay
unchanged, reads each reference image to name the replacement character, writes both into a
frozen prompt and renders. You can override any of it; nothing is ever invented silently.


## Competition requirements — repository guardrails ready, submission pending

The repository guardrails below are verified continuously. The actual contest submission, demo video,
try-it link, social-post link and feature-credit consent are **pending** until they exist as real
artifacts; this table does not claim an entry has been submitted.
Public-read access and reviewed integration to the default branch are also pending;
see [release gates](docs/release-readiness.md).

The [current official rules](https://comfy.org/open-source-higgsfield) allow ComfyUI
"entirely local", Comfy Cloud, the Developer Platform, Router, SDK, or a mix.
**Entirely local execution is allowed. A deployed try-it link is optional**, though
strongly encouraged. The official SDK remains our chosen transport, not a claim
that the contest requires managed hosting. Most Innovative explicitly includes
"novel custom node packs"; our pack must demonstrate useful original behavior,
not merely carry a new name. Cloud deployment remains a product goal, with a
prepared environment and real acceptance required before we claim it works.

| Requirement | Current evidence / submission state |
| --- | --- |
| Built with **ComfyUI**, using any allowed hosting option | our chosen transport is the official `comfy_sdk`; the proxy bridges API v2 to self-hosted ComfyUI. Remote target configuration exists; real managed deployment acceptance remains pending |
| Open-source licence and enough setup detail to run it elsewhere | [Apache-2.0](LICENSE), [local setup guide](docs/local-setup.md), `bash scripts/setup.sh --with-proxy` |
| Workflow files | [`workflows/`](workflows/README.md) — API-format app graphs plus the pinned vendor FLUX 3 source, checked by tests |
| Other tools, models and techniques explained in the demo video | script/content: pending; the current list is under *Techniques the demo explains* |
| Lawful, SFW, no unlicensed IP or likenesses | demo fixtures, prompts and tracked screenshot rights: pending human review; the source-code licence is not automatic media clearance |
| One submission per person | one final entry will be prepared; **not submitted** |


## Techniques the demo explains

The competition requires the combined techniques to be explained in the demo video:

- **Comfy SDK** for every submission, plus the `comfy-api-proxy` bridge to self-hosted ComfyUI
- **FLUX 2 Klein** (Black Forest Labs) as the first-frame image editor in LTX Studio
- **LTX 2.5 + Ripple FFAF IC-LoRA** as the motion stage in LTX Studio
- **MiniMax H3**, two-pass sampling, with the **Character Swap LoRA `h3_character_swap_v1.5` by akatz-ai** in H3 Studio
- an optional **local vision model** (`Qwen3-VL-2B-Instruct`, 4-bit quantization) that reads the H3 source clip and references to write descriptions frozen into the take

> **Commercial use needs separate model licences.** The weights this project runs are not all
> licensed for paid work, and two of them are the reason to read carefully:
>
> - **FLUX.2 Klein 9B** (the first-frame editor) is under the **FLUX Non-Commercial License** —
>   commercial use requires a licence from Black Forest Labs.
> - **MiniMax H3** (the H3 studio) is under the **MiniMax H3 Community License**, whose Applicable
>   Territory **excludes the European Union**, the United Kingdom, the Republic of Korea and the
>   United States, and which extends that restriction to the outputs. Operating from the EU, the H3
>   studio is not covered.
>
> The **LTX 2.5 + Ripple** path is the one licensed for commercial work here: Lightricks grants
> royalty-free commercial use below 10 M$ of annual revenue.
>
> Contest eligibility is a different question: the organizers confirmed that non-commercial weights
> qualify, because what matters is that the models can be downloaded and run locally. Read
> [Model licences](docs/validation/model-licences.md) before selling anything produced with this
> tool, and [the H3 license gate](docs/validation/h3-license-gate.md) for the H3 specifics.


## Current MVP: Character Recast with LTX 2.5 + Ripple

The first working product path is a local-first **visible-character recast**. Its first-frame editor is FLUX.2 Klein from **Black Forest Labs**; LTX 2.5 + Ripple carries that approved image edit through motion.

```
source video + character reference(s) + optional directions
        → edit frame 0 with FLUX.2 Klein image editing
        → propagate with LTX 2.5 + Ripple FFAF IC-LoRA
        → previewable edited video
```

The target is an open, local-first video transformation studio. **Character Recast is its first active mode**, not the whole product category: it uses optional reference images to guide the first-frame edit, then propagates it. We do not claim reliable object swap, wardrobe editing, motion transfer, or generic replacement until each has its own validated video path.


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

For both engines, use the [executor setup guide](docs/executor-setup.md) and the
source/version selections in `dependencies.json`. The reference executor reports
ComfyUI0.42.0; that is not a measured minimum-version promise. Check the actual
classes and loader choices with `scripts/check_dependencies.py --engine h3` or
`--engine ltx`. `--with-descriptions` explicitly includes the optional H3 vision
prerequisites; it does not attest that their HF files are already downloaded.


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
# The launcher pins the SDK to this local proxy by default.
bash scripts/run_app.sh
```

Open `http://127.0.0.1:8000`. Both services bind to loopback only. The launcher requires Python 3.12 and clears inherited `PYTHONPATH`.

Open **Settings** (`/settings`) to configure the shared API-v2 target and a write-only API key, explicitly test connectivity, and save when no processing is in flight. Saved settings take precedence; otherwise `OPENGENJUTSU_COMFY_BASE_URL` and `COMFY_API_KEY` bootstrap the app, with a local proxy default. Ambient SDK targets never silently select Cloud. The SDK environment is scoped to client construction, then restored. Test and Save do not submit generation. Remote connection success is distinct from verified node/model inventory and a real Cloud render. See the [setup guide](docs/local-setup.md).

The collapsed **Models** section maps LTX/H3 Swap loader roles to compatible files
under your target's own names. Test explicitly for loader-specific suggestions,
then Save. No files are renamed or installed; family/precision compatibility is
your responsibility. Aliases are target-scoped and new recipes freeze their
filenames; historical replay does not consult today's model choices.


---

## Models

The installer reads `dependencies.json` for **all 15 fixed Swap file roles**:
LTX/Ripple **including FLUX first-frame editing**, and H3. Each source is pinned
to an upstream revision, published size and SHA-256. These are upstream LFS
metadata, not a claim that local installed files have already been measured.

```bash
# Plan only by default: no network requests or model-directory writes.
env -u PYTHONPATH .venv/bin/python scripts/download_models.py --comfyui /path/to/ComfyUI
# Explicit download, on the ComfyUI executor host (choose ltx, h3, or all):
env -u PYTHONPATH .venv/bin/python scripts/download_models.py --comfyui /path/to/ComfyUI --engine h3 --download
```

Run this where the executor's existing `models/` directory is accessible; an HTTP
endpoint is not a filesystem installation path. `--dry-run` always prevents writes,
even with `--download`. Existing files are never replaced: they are validated
against exact Safetensors layout, size and SHA-256 before being skipped; incompatible
files produce a failure and remain untouched. Failed partial files are retained.
Successful staging is retained as a hardlink, not another copy. The POSIX downloader
refuses destination symlinks and requires enough free disk space for each file.

**FLUX Klein's upstream repository is gated.** Obtain the exact planned file through
your authorized upstream account and place it at the printed destination before
installing LTX/all; the CLI accepts no credentials and bypasses no access controls.
This fixed-file installer does **not** install custom nodes, optional vision HF
folders, Characters or native continuity models, and does not infer readiness from
file presence alone. See [executor preparation](docs/local-setup.md#prepare-fixed-swap-weights)
and run the dependency checker against your target. No model weights ship in Git.

| File | Folder | Role |
|---|---|---|
| `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` | `diffusion_models` | LTX 2.5 video model |
| `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` | `text_encoders` | LTX text encoder |
| `ltx-2.5-video-vae-conv-bf16.safetensors` | `vae` | video VAE |
| `ltx-2.5-audio-vae-bf16.safetensors` | `vae` | audio VAE |
| `LTX25_Ripple_v11.safetensors` | `loras` | FFAF propagation adapter |

The image-edit stage additionally requires the ComfyUI-compatible FLUX.2 Klein 9B checkpoint, text encoder, and VAE named in `src/core.py`. Those editor files are not auto-downloaded by this script yet; install them through the relevant official/ComfyUI model source and review their license terms. The gated LTX in/outpainting IC-LoRA is **not** required by this Ripple-based MVP.

### Check what a ComfyUI machine is missing

The complete list — custom node packs, models, LoRAs and the core nodes we depend on — is
[`dependencies.json`](dependencies.json), and the same list is readable in
[docs/dependencies.md](docs/dependencies.md). Verify a machine against it:

```bash
python3 scripts/check_dependencies.py --host http://127.0.0.1:8188
python3 scripts/check_dependencies.py --host <url> --include-planned   # + the character generator
```

It names the pack that owns a missing node, tells an out-of-date ComfyUI apart from an incomplete
one, and exits non-zero so it can gate a deployment.


---

## Run the app

```bash
# Keep the proxy running in its own terminal (see Install).
bash scripts/run_app.sh
```

Then open `http://127.0.0.1:8000`, choose a source video and a character reference, and generate **without typing a prompt**. **Add directions** is collapsed by default and optional: open it to refine the recast or describe a text-only edit without a reference. A closed directions editor is excluded from submission. Reveal a second reference only when needed; person-mapping hints remain optional. The backend compiles a versioned reference-recast instruction for FLUX and keeps LTX's propagation instruction separate. Both effective prompts and the original optional brief are recorded for replay; see [prompt contracts](docs/architecture/prompt-profiles.md).

The Creative Studio previews local media, keeps the active job ID across reloads, translates real pipeline stages, and exposes a result MP4. Completed takes show **Source → FLUX anchor → Motion result**; the anchor is the actual image passed to Ripple, not a reconstructed video frame. Older takes without recorded anchors are labeled honestly. **Take Capsule** records the local recipe, cuts and asset SHA-256 fingerprints and supports linked local replay. It never bundles private media or promises pixel-identical output. Studio HD targets approximately 0.9 megapixels at the source aspect ratio with 16 Ripple steps. Ripple strength remains advanced; **1.35 is a validated starting point on a controlled single-subject fixture**, not a universal optimum.

Check `GET /api/readiness` before submitting a job. `GET /health` proves only that
the app process is alive; it does not validate the proxy, upstream, nodes or models.

### H3 Studio (experimental)

The engine switch now links to `/h3`. H3 is available by default but can be
administratively disabled with `OPENGENJUTSU_H3_STUDIO_ENABLED=0`. Its readiness
check is target-specific and blocks generation until the configured Comfy target
reports the H3 graph's nodes and models as available. It accepts one continuous
shot and one character reference, normalizes to 24 fps, derives a 32-aligned
render canvas from source aspect ratio (each input edge at most 512 px), and
upscales that canvas 2×. H3 weights and custom-node availability remain target
requirements; a successful self-hosted render does not prove Comfy Cloud support.
The Studio shows real queue/run states and preserves source audio when present.
See [H3 runtime validation](docs/validation/h3-studio-runtime.md) for tested
fixtures, measurements, known visual limits and the actual model license.

The CLI in `src/genjutsu.py` is a legacy LTX 2.3 prototype and is not the current app entry point.

---

## Documentation

- [Local setup and troubleshooting](docs/local-setup.md) — Python 3.12, FFmpeg, opt-in proxy, remote upstream and readiness
- [Workflow files](workflows/README.md) — the exported API-format graphs the app submits, and how their asset placeholders are substituted
- [Documentation index](docs/README.md) — the map of everything under `docs/`, with what is current and what is historical
- [Competition roadmap](docs/plans/competition-roadmap.md) — the requirements checklist, what is done, and the decisions still open
- [Creative Studio UI architecture](docs/ui-architecture.md) — product workflow, engine visual identity and honest local-sharing boundary
- [Reference intelligence plan](docs/plans/2026-10-16-reference-intelligence.md) — opt-in Qwen-VL preflight, review gate and target-visibility scope
- [Open Weights runtime evidence contract](docs/validation/open-weights-runtime-contract.md) — declared models/nodes/transport, live readiness gate and submission-proof boundaries
- [Competition UX/viral-readiness audit](docs/audits/2026-10-16-competition-ux-gap.md) — verified gap analysis and follow-up gates
- [`src/app.py`](src/app.py) — local UI, upload endpoint, job tracking and result route
- [`src/core.py`](src/core.py) — job persistence and per-shot pipeline orchestration
- [`src/take_capsule_api.py`](src/take_capsule_api.py) — path-free local recipe/provenance manifest and linked replay
- [`src/graphs.py`](src/graphs.py) — FLUX.2 Klein and LTX/Ripple API-format graphs
- [`src/comfy_transport.py`](src/comfy_transport.py) — official SDK target, execution and downloads
- [`src/segments.py`](src/segments.py) — per-shot asset transfer, padding and exact frame restoration
- [`scripts/download_models.py`](scripts/download_models.py) — manifest-driven, explicit Swap weight installation
- [ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo)
- [ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite)
- [ComfyUI-KJNodes](https://github.com/kijai/ComfyUI-KJNodes)


---

## Character Reference Status

The Creative Studio accepts up to two optional PNG/JPEG/WebP character references in the main job form. It shows one calm primary control by default and discloses the second only when the user explicitly adds another visible character. Each reference can have an optional target hint; reference order is preserved through the job metadata and FLUX conditioning chain. Assets are stored with the job and transferred as Comfy assets for each shot. Unit and HTTP-contract tests cover this route.

This is visual conditioning, not a guaranteed reference-to-person assignment. In particular, a reference image does not solve an absent or occluded target; that requires a separately validated anchoring/tracking strategy.

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
    app.js             — source preview, job states and local export actions
    reference-controls.js — progressive optional second-reference controls
    studio-utils.js    — shared browser helpers
  templates/index.html — English-first Creative Studio UI
  genjutsu.py     — Legacy LTX 2.3 CLI prototype (not current entry point)
tests/            — Unit and regression tests (unittest)
scripts/
  download_models.py — Plan / explicitly install fixed Swap weights
```

**Pipeline**: `detect_scenes()` → `edit_segment()` per shot → `merge_segments()` → `upscale_video()`

The application ignores inherited `COMFY_BASE_URL`. Its default is local; change the target explicitly in Settings or bootstrap it with `OPENGENJUTSU_COMFY_BASE_URL`. Credentials stay server-side in the private ignored settings store, never in a capsule or a browser-readable configuration response.

The app has target-aware readiness for a local proxy, remote self-hosted proxy, Comfy Cloud and API v2 deployments. **Only the self-hosted path has live render evidence**; Cloud/deployment authentication branches have tests, but required nodes/models and real rendering must still be validated on the selected target. Queueing behind an existing Comfy job is allowed with an on-screen waiting notice. No specific server cache setting is required.

## Current Evidence

- A real two-shot run was submitted through the web form, processed by FLUX.2 Klein and LTX/Ripple, downloaded, and played through to the end in Chromium: 121 frames, 24 fps, 768×416. Shot padding is removed before assembly; the app restores source audio when present.
- **Visual quality is not validated:** the corrected run preserves the scene cut, but recolors/armors the tiger despite instructions to preserve it. Successful execution is not a successful selective edit or a contest-ready result.
- CPU tests are self-contained; they do not require the private development clip. They do not prove GPU quality, reference-image behavior on real footage, Cloud compatibility or licensing eligibility.
- The Creative Studio UI is implemented and browser-checked for desktop/mobile layout, source preview and HTTP/API integration. Local Download and Copy caption are real actions; **public social sharing is not implemented** because no hosted, recipient-accessible result URL exists.
- The public studio deliberately focuses on LTX and FLUX. Future studio modes are not named or advertised until they have a real backend and an end-to-end validation.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Write tests first (TDD)
4. Run `env -u PYTHONPATH .venv/bin/python -m unittest discover -s tests -v`
5. Commit with descriptive messages
6. Open a PR

## License

Apache-2.0 — see [LICENSE](LICENSE).

This repository is Apache-2.0. LTX 2.5, Ripple, FLUX.2 Klein, experimental MiniMax H3 and all ComfyUI extensions retain their own licenses and acceptable-use terms; the app license does not license model weights. **Obtain any required commercial license before using models commercially.** H3 also has territorial restrictions: read the [official H3 license](https://huggingface.co/MiniMaxAI/MiniMax-H3/raw/main/LICENSE) and the [H3 scope note](docs/validation/h3-license-gate.md). Organizer guidance relayed by the user accepts locally downloadable/runnable models, including non-commercial models and H3, for contest eligibility; this is not permission for unrestricted commercial or territorial deployment. No weights are bundled.
