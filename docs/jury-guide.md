# OpenGenjutsu — two-minute jury guide

**v0.1.0-alpha.1 · Local-first alpha · [Apache-2.0 application](../LICENSE).**

**The idea:** create a character, recast footage, then return to the saved take
and keep creating. The differentiator is the return journey: an H3 take can retain
the state needed for a continuation, rather than leave you with only a finished MP4.

## What to demonstrate

Use existing results for the short tour; GPU generation is not a real-time
promise. The **110-second private film has been rendered** at 1920×1080,
30 fps, H.264/AAC, and decoded end to end without errors. See the
[film verification record](validation/jury-film-2026-10-27.md). The film uses
distinct Character, H3 Swap, native-continuation and LTX examples; it does not
claim they are one end-to-end generation. Explanatory English subtitles are
available privately, not a transcript of generated dialogue.

**The creator rejected this first cut** for repetition, ordering, weak structure,
soundtrack/narration omissions and unsuitable or outdated examples. It is a
historical technical record, not the competition demonstration. The
[V2 production plan](plans/2026-10-27-jury-v2.md) requires a new media selection
and a structured, narrated edit with music.

Media publication and human pacing/audio review remain open. This checkout has
no public demo-video link; no publication or contest submission is implied.

| Step | Show in the running app | What the reviewer should notice |
| --- | --- | --- |
| **Create** | `/characters`: idea controls, selected image, Attempts/Saved shelf. Keep a named character, then **Use in studio**. | A reusable reference, not a disconnected image download. There are 18 wardrobe variations; portrait/full-body/turnaround are views, not separate style engines. |
| **Recast** | `/` for LTX 2.5 + Ripple, or `/h3` for H3. Show the source, one or two ordered references and an actual completed result. | Explicit source/reference choices and a frozen receipt. Directions are optional. Opening a workspace does not start a render. |
| **Return and continue** | For an H3 Swap, **Advanced controls → Save native state too** is opt-in. Reopen its native version in `/timeline`; show the parent, child and grandchild. | A saved place to resume creating. The original remains; a continuation is a new take, not an overwritten MP4. |

A real local **root → child → grandchild** chain was captured, reopened and played;
see the [current native H3 evidence](validation/native-take-workspace.md#current-alpha-status--native-h3-capture-and-forward).
The family bytes stay private; the report is evidence, not downloadable demo footage.

## Evidence: read four levels separately

| Level | Evidence | What it does not establish |
| --- | --- | --- |
| **CPU** | [Repository guards](../tests/test_competition_requirements.py), [presentation checks](../tests/test_jury_presentation_docs.py) and API/file contracts | GPU execution, visual quality or publication |
| **Browser** | [Visible product slices](validation/visible-product-slices.md) and [native reopening](validation/native-take-workspace.md) | A new GPU install or every current UI state; older records identify their historical scope |
| **GPU** | Local [H3 runtime](validation/h3-studio-runtime.md), [LTX reference run](validation/2026-10-16-ltx-multi-reference-gpu.md) and the later H3 continuation chain | All operations, other hardware, remote/Cloud execution or universally transferable state |
| **Human** | Still-open review of identity, motion/audio joins, source/reference permissions and final media | A green test suite cannot grant likeness rights or approve artistic quality |

## Limits that matter

- **Before**, **bridge**, **refine** and **native LTX** GPU acceptance remain open.
  H3/LTX state is **not interchangeable**; complete cross-target portability and
  real **Cloud** rendering are not accepted.
- Characters and Timeline remain work in progress. Optional face refinement uses
  separate face-only conditioning, is off by default and may change facial details.
  No photorealism or identity guarantee follows from its completion.
- H3 native capture retains MP4 + MCTX + COND, frozen choices and lineage. The
  **upstream** engines provide the state/conditioning mechanisms; OpenGenjutsu
  connects them into a user journey, not a newly invented file format. Native and
  finished Swap videos can differ in duration/audio. Public receipt JSON is
  **not a complete Take backup**.
- Export/download and browser-supported file sharing are distinct from hosting.
  An X intent prepares caption text; it **does not upload the video** automatically.
- Model terms remain separate from the application licence; see the single
  [model-licence reference](validation/model-licences.md). Media approval, anonymous
  repository access and final submission remain [release gates](release-readiness.md).

## Run it yourself

The commands below are the same local path as the [README](../README.md#install)
and [executor guide](executor-setup.md#5-check-actual-inventory-without-rendering).
Start with [local setup](local-setup.md) for troubleshooting.

<details>
<summary>Prerequisites, installation and launch commands</summary>

**Prepare these separately:** Git/Bash, `uv`, Python 3.12, FFmpeg/ffprobe, and a
trusted GPU ComfyUI executor with the selected engine's **custom nodes** and
**model weights**. The app uses official Comfy SDK 0.5.x and an API-v2 proxy for
self-hosted execution. The installer **does not install ComfyUI**, custom nodes or
model weights, and does not start services. Model filenames and node revisions
are declared in [`dependencies.json`](../dependencies.json), not bundled weights.

From an authorized checkout:

```bash
git clone https://github.com/lvsas/Open-Source-Higgsfield-Competition.git
cd Open-Source-Higgsfield-Competition
bash scripts/setup.sh --with-proxy
```

`bash scripts/setup.sh` alone installs app dependencies; `--with-proxy` explicitly
adds the local proxy. Keep ComfyUI and node requirements in the executor's own
environment, not the app's `.venv`.

After preparing and starting ComfyUI, run the proxy in terminal A:

```bash
export COMFYUI_URL=http://127.0.0.1:8188
env -u PYTHONPATH .venv/bin/comfy-api-proxy run \
  --comfyui "$COMFYUI_URL" --host 127.0.0.1 --port 8189
```

In terminal B, from the same checkout:

```bash
bash scripts/run_app.sh
```

Open <http://127.0.0.1:8000>. The app and proxy bind only to loopback. If the GPU
executor is elsewhere, use your trusted upstream address; do not expose raw
ComfyUI publicly.

Open **Settings** (`/settings`) for the API-v2 target, **write-only** key and
compatible target-specific LTX/H3 Swap model filenames. **Test connection** checks
the proposed target without saving; **Save settings** is explicit and blocked
while processing is active. Neither action submits a render. Opening Settings
**does not submit generation**. A connection success is not proof of node/model
inventory or a successful render. Native continuity/Characters have separate
prerequisites from the fixed Swap mappings.

</details>

<details>
<summary>Check inventory and run bounded documentation guards</summary>

These inventory checks do not render. Use the executor's raw ComfyUI URL, not
its SDK proxy URL, and select only the engine you intend to exercise:

```bash
env -u PYTHONPATH .venv/bin/python scripts/check_dependencies.py --host http://127.0.0.1:8188 --engine h3
env -u PYTHONPATH .venv/bin/python scripts/check_dependencies.py --host http://127.0.0.1:8188 --engine ltx
```

The scoped Swap checks do not attest to native continuation readiness. Optional H3
vision descriptions need additional dependencies; the
[executor guide](executor-setup.md) describes their explicit check. File/loader
availability does not establish CUDA compatibility or render success.

From the repository root, no GPU required:

```bash
env -u PYTHONPATH .venv/bin/python -m unittest discover -s tests -p 'test_jury_presentation_docs.py' -v
env -u PYTHONPATH .venv/bin/python -m unittest discover -s tests -p 'test_competition_requirements.py' -v
```

The presentation guard resolves local Markdown links, anchors and images across
the README, this guide, release checklist and both setup guides; it also checks
version, setup commands, claim boundaries and credential/private-network patterns.
It is a bounded current-file check, not a history, image-content or rights audit.
The competition guard additionally checks tracked README assets/links and exported
workflow consistency. Maintainers must stage the exact reviewed documentation and
approved assets before claiming the Git-tracking gates pass:

```bash
env -u PYTHONPATH OPENGENJUTSU_JURY_REQUIRE_TRACKED=1 .venv/bin/python -m unittest discover -s tests -p 'test_jury_presentation_docs.py' -v
```

File existence and Git tracking are deliberately separate. No test changes the
index, publishes a film or submits an entry.

</details>
