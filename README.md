# Open Jutsu Studio

## Create. Swap. Continue. Share.

**An open-source video studio for putting your characters into footage—and keeping a take you can return to.**

Create a character or bring your own reference. Swap the cast of a clip, reopen
an H3 take to continue the story, then share a vertical comparison Reel.

**Local-first · Your GPU, your footage · [Apache-2.0](LICENSE)**

[Install](#install) · [Creative loop](#the-creative-loop) · [Roadmap](ROADMAP.md) · [Documentation](docs/README.md)

<p align="center"><img src="docs/readme/demo.gif" alt="Three moments from the studio: the two reference boards, the recast shot, and the stitched continuation" width="820"></p>

*Recorded in the running application on 30 October 2026: the two reference boards,
a real Swap result, then one continuous clip — the end of a Take followed by the
continuation it produced. Nothing here is a mock-up.*

![H3 Studio workspace, awaiting source video and character references](docs/readme/h3-studio-current.png)

*The same studio, empty: an interface capture, not a generated-result quality claim.*

## Install

One path. Use it, then read the exceptions only if one applies to you.

```bash
git clone https://github.com/lvsas/OpenJutsuStudio
cd OpenJutsuStudio
make setup COMFYUI=/path/to/ComfyUI   # app, node packs and models
make check                            # what is still missing (exit 1 if anything)
make run                              # proxy + studio on 127.0.0.1:8000
```

Open <http://127.0.0.1:8000>. `make run` starts the SDK proxy in the right order and
stops it again on Ctrl+C, so there is only one command to remember.

**What each step touches:** `make setup` installs the app environment, then the node
packs declared in `dependencies.json` (registry archives are hash-checked), then the
weights for the engines you picked. It never overwrites an existing pack, never
starts a service, and never installs ComfyUI itself. `make check` installs nothing: it
names what is still missing. `make run` serves the studio and nothing else.

**What it needs:** a GPU machine running ComfyUI, about 24 GB of VRAM, and FFmpeg. No
account, no credits, nothing calls home.

### Exception 1 — you are on Windows

There is no `make`. Run the same steps in Python:

```bash
python scripts/launch.py
```

### Exception 2 — you want the studio in a container

The image runs the app only. ComfyUI and its weights stay where they are.

```bash
docker compose up --build          # http://127.0.0.1:8000
```

`COMFY_BASE_URL` (default `http://host.docker.internal:8189`) points at your proxy.
The port is published to loopback on purpose: the app has no authentication. Takes and
media live in `./work`, mounted from the host, so recreating the container keeps them.
This does **not** remove the ComfyUI requirement — `make check` still names what the
executor lacks.

### Exception 3 — you want to do every step by hand

`make setup` is not magic. This is exactly what it runs:

```bash
bash scripts/setup.sh --with-proxy
export COMFYUI_URL=http://127.0.0.1:8188
env -u PYTHONPATH .venv/bin/comfy-api-proxy run \
  --comfyui "$COMFYUI_URL" --host 127.0.0.1 --port 8189
bash scripts/run_app.sh
```

The full walkthrough, including the executor side, is in
[local setup](docs/local-setup.md).

### Exception 4 — ComfyUI runs on another machine

Run `make setup` and `make run` on the app host, then point the app at that machine
instead of the local proxy:

```bash
export OPENGENJUTSU_COMFY_BASE_URL=http://comfyui-host:8189
```

The target must speak the Comfy SDK v2 API. A stock ComfyUI serves v1, which is why the
proxy exists: the application speaks v2, the proxy translates, and both stay on
loopback.

## The creative loop

1. **Create or bring a character.** Open Characters (`/characters`) to generate
   with FLUX 3 Klein, or use your own reference image.
2. **Swap the cast.** In LTX Studio (`/`) or H3 Studio (`/h3`), add footage and
   one or two ordered references, then preview the result.
3. **Continue the take.** Every new H3 Swap automatically retains its continuation state.
   Open that take in Timeline (`/timeline`) and create a continuation.
4. **Share the moment.** Preview and download a vertical before/after Reel.
   Native file sharing depends on browser support; download is the fallback.
   Sharing does not automatically publish to social platforms.

### A take is more than an MP4

The H3 path retains the **MP4 + MCTX + COND** family, references, frozen
recipe and parent lineage. Open Jutsu Studio connects native-file publication through
the SDK, reopening and continuation in one workspace. A recipe records the render;
**JSON alone is not the native state needed to continue it**. A social Reel is
not a complete native backup. Upstream engines define the state formats: H3 and
LTX state is not interchangeable.

## Current boundaries

- **New H3 Swaps and re-runs always retain native state.** Missing state publication
  fails explicitly; an existing MP4 alone cannot recreate missing MCTX/COND files.
- **LTX native continuation is not delivered.** Timeline forward continuation is
  experimental and engine-specific, not a promise that every editing mode works.
- **Character/library handoffs exist.** End-to-end browser acceptance and clearer
  navigation are ongoing work; new recipe experiments need saved-Capsule compatibility.
- Render completion does not guarantee identity, selective editing, motion or sound
  quality. Live Cloud execution and broad cross-target portability are not verified.

[Roadmap](ROADMAP.md) · [Workflow and evidence boundaries](docs/README.md)

## Requirements

- Version **v0.1.0-alpha.1**, development preview, grounded in `src/app_release.py`.
- Git/Bash, **uv**, **Python 3.12**, and **FFmpeg/ffprobe** on `PATH`.
- A separately prepared GPU **ComfyUI** executor with the chosen engine's custom
  nodes and model weights. **24 GB VRAM is recommended**, not a fit guarantee.
- Official **Comfy SDK 0.5.x** transport; the local setup uses an API-v2 proxy.

See [executor setup](docs/executor-setup.md) for engine-specific prerequisites,
[dependencies](docs/dependencies.md) for file roles, and
[weight installation](docs/local-setup.md#prepare-fixed-swap-weights) for the explicit downloader.
No model weights ship in this repository. There is no Docker installation in this preview.

## Documentation

[Setup and troubleshooting](docs/local-setup.md) · [Executor preparation](docs/executor-setup.md) ·
[Dependencies](docs/dependencies.md) · [Workflows](workflows/README.md) ·
[Documentation](docs/README.md) · [Roadmap](ROADMAP.md)

## Built on / credits

An independent open-source video studio, built for the
[Open Source Higgsfield Competition](https://comfy.org/open-source-higgsfield) as
an answer to the character-swap idea — not affiliated with, endorsed by, or
connected to Higgsfield. It ships connected Character and Timeline workspaces,
built with **ComfyUI** and the
[Comfy Developer Platform](https://comfy.org/platform), using official Comfy SDK
transport for self-hosted execution.

- **Black Forest Labs** — FLUX 3 Klein for Characters; FLUX 2 Klein for LTX anchors.
- **Lightricks / Ripple** — LTX 2.5 and the Ripple FFAF IC-LoRA motion path.
- **MiniMax / akatz-ai** — H3 and the `h3_character_swap_v1.5` Character Swap LoRA.
- **ComfyUI and extension authors** — execution, state mechanisms and node packs;
  see [sources and dependencies](docs/dependencies.md).
- **Open Jutsu Studio** — the connected studio and continuity-file publication/reopening nodes.

Prepared for the [Open Source Higgsfield Competition](https://comfy.org/open-source-higgsfield).
Entirely local execution is allowed. A deployed try-it link is optional.
The innovation category includes novel custom node packs. Combined techniques:
FLUX character/reference editing, LTX + Ripple propagation, H3 Swap/native continuation,
SDK artifact transport and local FFmpeg Reel assembly.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for GPU-free checks and contribution boundaries.
Report reproducible steps and sanitized diagnostics, not API keys or private native backups.

## License

Application code: **Apache-2.0**, see [LICENSE](LICENSE). Model weights and third-party
extensions have separate terms; obtain any required permissions before commercial
use or redistribution. See [component licences](docs/model-licences.md).
