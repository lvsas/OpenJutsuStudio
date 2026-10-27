# OpenGenjutsu — Create a character. Recast a scene. Continue the take.

**v0.1.0-alpha.1 · Early development preview, not a finished 1.0 product.**

**An open-source video studio for keeping the story going, not starting over.**
Turn an idea into a character, put them into footage you already shot, then
reopen a saved H3 take and continue from where you left off.

**[Review in two minutes](docs/jury-guide.md) · [Install and run](#install) ·
[See verified scope and limits](#verified-scope-and-limits)**

- **Create a reusable character** with FLUX 3 Klein; keep a named reference for either Swap studio.
- **Recast your footage** with LTX 2.5 + Ripple or MiniMax H3 and up to two ordered references.
- **Return to the take, not just the MP4.** Opt into H3 native capture, reopen it
  in Timeline and generate a continuation while keeping the original.

Local-first alpha · official Comfy SDK transport · [Apache-2.0](LICENSE).

![Current H3 Studio workspace, awaiting source video and character references](docs/readme/h3-studio-current.png)

*Actual v0.1.0-alpha.1 interface, captured on 27 October 2026. This empty
workspace shows the current controls, not a generated result or quality claim.*

## The creative loop

1. **Create a character** in `/characters`. Generate with FLUX 3 Klein, choose an
   attempt and keep a named reference. Explore 18 wardrobe variations, or bring
   your own reference and skip straight to Swap.
2. **Recast a scene** in LTX Studio (`/`) or H3 Studio (`/h3`). Add your footage
   and one or two ordered character references. Directions are optional; preview
   the result and decide what to keep.
3. **Continue the take** in `/timeline`. For H3, enable **Save native state too**
   before generating, reopen the native take, then create a continuation. Keep the
   original, follow its child takes, and assemble selected clips into an MP4.

### More than a video to download

An opt-in H3 take keeps the native **MP4 + MCTX + COND** family, its frozen
recipe, references and parent lineage. Reopen that saved state to continue
creating instead of starting from an exported MP4. A real local
**root → child → grandchild** chain has been exercised.

ComfyUI and the upstream engines provide the state and conditioning formats;
OpenGenjutsu connects capture, reopening and continuation into one workspace.
An MP4 alone cannot restore that state, and H3/LTX state is not interchangeable.
See [native H3 evidence](docs/validation/native-take-workspace.md) and
[artifact integrity](docs/architecture/timeline-artifacts.md).

## Verified scope and limits

| Workspace | Available in this alpha | Experimental / not accepted |
| --- | --- | --- |
| **Characters** | FLUX 3 Klein generation, named references and reuse in either Swap studio | Optional face refinement uses separate face-only conditioning and is off by default; identity and texture quality need review |
| **LTX Studio** | FLUX 2 Klein first-frame edit → LTX 2.5 + Ripple propagation | Native LTX continuation and broader editing modes |
| **H3 Studio** | MiniMax H3 two-pass character swap with 1–2 ordered references; opt-in native capture | Capture requires its own nodes/models; native and finished Swap videos can differ in duration/audio |
| **Timeline** | Reopen saved H3 takes, continue forward, retain lineage and assemble/export clips | Before, bridge, refine, complete cross-target portability and real Cloud execution |

All workspaces remain alpha. A completed render is not approval of identity,
selective editing, motion or audio quality. The final demonstration film is not
ready. For evidence levels and publication gates, see the [jury guide](docs/jury-guide.md)
and [release checklist](docs/release-readiness.md).

## Requirements

- Git/Bash, **uv**, **Python 3.12**, and **FFmpeg/ffprobe** on `PATH`.
- A separately prepared GPU **ComfyUI** executor with the chosen engine's custom
  nodes and model weights. **24 GB VRAM is recommended**, not a fit guarantee.
- Official **Comfy SDK 0.5.x** transport; the local setup uses an API-v2 proxy.

See [executor setup](docs/executor-setup.md) for engine-specific nodes/models,
[the dependency inventory](docs/dependencies.md) for file roles, and
[weight installation](docs/local-setup.md#prepare-fixed-swap-weights) for downloads.
No model weights ship in this repository.

## Install

Repository access may require your own authorized GitHub account.

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

Open <http://127.0.0.1:8000>. App and proxy bind to loopback only. The launcher
requires Python 3.12 and clears inherited `PYTHONPATH`.

Open **Settings** (`/settings`) to test and save the API-v2 target, write-only API
key and compatible target-specific LTX/H3 Swap model filenames. Test/Save do not
submit generation. Connection success alone does not establish engine readiness;
see [local setup and troubleshooting](docs/local-setup.md).

## Documentation

| Start here | Covers |
| --- | --- |
| [Local setup](docs/local-setup.md) | Installation, proxy, Settings and troubleshooting |
| [Engine / executor setup](docs/executor-setup.md) | Custom nodes, model roles and readiness checks |
| [Native H3 takes](docs/validation/native-take-workspace.md) | Capture, reopening, forward continuation and evidence boundaries |
| [Workflows](workflows/README.md) | Exported API graphs and their source models |
| [Jury guide](docs/jury-guide.md) · [Release checklist](docs/release-readiness.md) | Demonstration techniques, evidence and submission gates |
| [Documentation index](docs/README.md) | Architecture, validation reports and historical plans |

## Built on / credits

An open-source rebuild of [Higgsfield Genjutsu](https://higgsfield.ai/genjutsu),
with connected Character and Timeline workspaces. Built with **ComfyUI** and the
[Comfy Developer Platform](https://comfy.org/platform), using official Comfy SDK
transport for self-hosted execution.

- **Black Forest Labs** — FLUX 3 Klein for Characters; FLUX 2 Klein for LTX anchors.
- **Lightricks / Ripple** — LTX 2.5 and the Ripple FFAF IC-LoRA motion path.
- **MiniMax / akatz-ai** — H3 and the `h3_character_swap_v1.5` Character Swap LoRA.
- **ComfyUI and extension authors** — upstream execution and state mechanisms;
  see [sources and dependencies](docs/dependencies.md) and the
  [continuity pack](docs/architecture/continuity-nodes.md).

Prepared for the [Open Source Higgsfield Competition](https://comfy.org/open-source-higgsfield).
Entirely local execution is allowed. A deployed try-it link is optional.
The innovation category includes novel custom node packs.
Submission and media publication remain separate [release gates](docs/release-readiness.md).

## Contributing

1. Fork the repository
2. Create a feature branch
3. Write tests first (TDD)
4. Run `env -u PYTHONPATH .venv/bin/python -m unittest discover -s tests -v`
5. Commit with descriptive messages
6. Open a PR

## License

Apache-2.0 — see [LICENSE](LICENSE).

The application licence does not license model weights or third-party extensions.
Their own terms apply; **obtain any required commercial licence before commercial
use**. See [model licences](docs/validation/model-licences.md) and the
[H3 scope note](docs/validation/h3-license-gate.md) for component and territorial
restrictions. No weights are bundled.
