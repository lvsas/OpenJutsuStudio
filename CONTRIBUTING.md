# Contributing to OpenGenjutsu

Keep changes focused, testable without inference hardware, and understandable to the next contributor. Discuss changes to public APIs, graph topology, recipe policies or artifact formats before implementing them. Contributions follow the repository's [MIT license](LICENSE); model weights and third-party assets have separate terms.

## Set up a development checkout

Run commands from the repository root in Bash (Linux, or WSL on Windows). Use Python 3.12, [uv](https://docs.astral.sh/uv/), and FFmpeg with both `ffmpeg` and `ffprobe` on `PATH`. For JavaScript checks, use Node.js 22 or newer; the supplied harnesses need no npm packages.

```bash
bash scripts/setup.sh --help
bash scripts/setup.sh
```

Setup creates/reuses `.venv`, installs `requirements.txt`, and creates `work/jobs` and `work/media`. It does **not** install ComfyUI, download weights, start services or submit renders. An incompatible or broken existing environment is rejected, not replaced. Inspect shared environments/symlinks before moving them; never delete a shared target to repair a checkout.

Use the project interpreter and clear inherited `PYTHONPATH` as shown below. Requirements are ranges, not a complete lockfile: this is a repeatable bootstrap procedure, **not** a bit-for-bit reproducible dependency resolution. Record Python, Node, FFmpeg and resolved package versions when reporting environment-dependent failures.

No GPU, ComfyUI server or proxy is needed for the checks below. The optional proxy installation (`bash scripts/setup.sh --with-proxy`), manual service startup and model prerequisites are documented in [local setup](docs/local-setup.md). Character multi-artifact publication currently requires Linux `renameat2` support; macOS is not an equivalent runtime for that path.

## Verify without a GPU or server

Start with this small, isolated contract set:

```bash
env -u PYTHONPATH .venv/bin/python -m unittest tests.test_setup tests.test_character_graphs tests.test_h3_studio_ui tests.test_share_reel_ui -v
bash -n scripts/setup.sh scripts/run_app.sh
git diff --check
```

The setup tests copy scripts into temporary trees and stub installers/launchers; they do not install packages or start services. The UI tests run their Node harnesses when Node is available and otherwise **skip** them. Run the harnesses directly to require JavaScript coverage:

```bash
node --experimental-default-type=module tests/h3_studio_contract.mjs
node tests/share_reel_ui_contract.mjs
```

For the complete CPU regression suite, use an isolated work root **before importing application modules**. `src/config.py` creates directories on import; `core.Job.save()` persists under `core.WORK`. This subshell also confines temporary fixtures and removes only its newly created test directory:

```bash
(
  TEST_ROOT="$(mktemp -d "${TMPDIR:-$PWD}/opengenjutsu-tests.XXXXXX")" || exit 1
  trap 'rm -rf -- "$TEST_ROOT"' EXIT
  mkdir -p "$TEST_ROOT/tmp"
  export TMPDIR="$TEST_ROOT/tmp" OPENGENJUTSU_WORK="$TEST_ROOT/work"
  unset COMFY_API_KEY COMFY_BASE_URL OPENGENJUTSU_COMFY_BASE_URL
  env -u PYTHONPATH .venv/bin/python -m unittest discover -s tests -v
)
```

Run this in your own development checkout, not against another developer's active workspace. To narrow it, replace `discover -s tests` with a module such as `tests.test_comfy_transport` or `tests.test_h3_capsule_compat`. Tests use the standard-library `unittest` runner; no pytest installation is required. FFmpeg media tests generate small synthetic inputs, including H.264 fixtures; missing tools can cause skips or failures. Some repository guardrails use Git's tracked-file index, so use a Git checkout rather than an archive and review missing/untracked-file failures explicitly.

### What passing tests establish

- Graph, recipe and capsule tests check contracts, integrity and compatibility.
- Transport tests mock SDK execution/downloads. `test_pipeline_integration.py` mocks orchestration dependencies; `test_h3_integration.py` combines real CPU media handling with mocked GPU inference. Their names do not make them live-render evidence.
- Node harnesses use DOM/HTTP doubles. They check state transitions and races, not browser layout, accessibility, native sharing support or visual quality.
- A real clean install is a separate manual check in a fresh checkout, without copying `.venv`, `.env*`, caches or generated `work/` content. Bootstrap mocks do not verify package downloads.

There is no checked-in CI workflow to substitute for these local checks. Report commands, outcomes and skips in the pull request; do not call a partial run the full suite.

## Find the right boundary

| Concern | Starting points |
| --- | --- |
| App registration, queue and shared job storage | `src/app.py`, `src/core.py`, `src/job_api.py` |
| LTX frame edit and propagation | `src/graphs.py`, `src/engines.py`, `src/segments.py` |
| H3 swap | `src/h3_graphs.py`, `src/h3_recipe.py`, `src/h3_pipeline.py`, `src/h3_api.py` |
| Character images and captions | `src/character_graphs.py`, `src/character_recipe.py`, `src/character_pipeline.py`, `src/character_api.py` |
| SDK transport and runtime checks | `src/comfy_transport.py`, `src/readiness.py`, `src/runtime_inventory.py` |
| Local H3 artifact integrity (Timeline foundation, not an editor) | `src/timeline_artifacts.py`, `src/safetensor_header.py`, `src/h3_conditioning.py`, `scripts/inspect_h3_artifacts.py` |
| Pages, shared styles and browser behavior | `src/templates/`, `src/static/`, `tests/*ui*.py`, `tests/*.mjs` |

See the [documentation index](docs/README.md) and [public roadmap](ROADMAP.md) for scope. Inspect source and tests before treating a proposed feature as shipped behavior.

### Graphs and the official SDK

Graphs under `workflows/` are **API-format** graphs (`class_type`/`inputs`), not canvas workflow exports. Application execution uses the official `comfy-sdk` (`>=0.5,<0.6`) through `Comfy`, `workflows.from_json`, SDK assets, `run`, exact output-node selection and artifact download. Preserve that path; a successful direct ComfyUI `/prompt` submission does not validate SDK upload, execution or retrieval.

After changing LTX/H3 builders, regenerate the three generated exports and review their diff:

```bash
env -u PYTHONPATH .venv/bin/python scripts/export_workflows.py
git diff -- workflows/
```

This command writes workflow files; it does not render. `tests/test_competition_requirements.py` checks that exports match their builders. `workflows/flux3-klein-official-t2i.json` is different: it is a digest-pinned vendor source, not a generated export. Change its adapter's allowed controls deliberately; a vendor update requires a reviewed migration and graph-contract tests. See [workflow documentation](workflows/README.md).

Extend H3 and LTX within their existing engine-specific recipe, graph, worker and API boundaries. H3 is an isolated worker, not an entry in the LTX `ENGINES` registry; Character generation is an image/caption workflow, not a video engine. Reuse shared storage and queue contracts without pretending the engines have identical capabilities. Timeline integration needs its own validated artifact/adapter contract and tests: a sidecar, roadmap or graph experiment does **not** establish a working Timeline editor or native continuation.

### Durable artifacts and backward compatibility

Freeze validated recipes/graphs and record artifact hashes and lineage before reporting success. Keep output paths server-owned, downloads bounded to declared output nodes, and partial failures non-destructive. Do not overwrite unrelated outputs or cancel other users' jobs.

Capsules are historical evidence. New schema/prompt-policy versions must retain version-aware readers for previously supported records; do not reinterpret old recipes with today's defaults. Separate reading historical evidence from replay validation: replay may reject an obsolete policy with an actionable reason and derive a new job instead of mutating its parent. Add legacy fixtures and tamper/missing-asset tests alongside current happy paths (see `tests/fixtures/character_recipe_v*_frozen.json` and `tests/test_h3_capsule_compat.py`). Never promise pixel-identical replay from a seed alone.

## Keep assets, secrets and paths private

- `.venv`, `work/`, `assets/`, generated PNG/MP4 files, caches and `.env*` are ignored, with explicit exceptions such as README screenshots. An ignore rule is not a security boundary and does not untrack existing files.
- Do not commit weights, user uploads, generated personal media, credentials, private addresses, absolute workstation paths or machine-specific/private model configuration. Use synthetic fixtures or small, licensed assets with documented provenance. Check that intentionally shipped assets are actually tracked.
- `OPENGENJUTSU_WORK` overrides local storage; set it before imports and keep test roots separate from live jobs. Patch `core.WORK` and any module-local imported storage aliases in tests that persist files. Mock SDK/model calls and readiness probes; a unit test must not submit inference or depend on a local server.
- The app uses a loopback SDK proxy by default. Saved Settings take precedence over the `OPENGENJUTSU_COMFY_BASE_URL` bootstrap override; inherited `COMFY_BASE_URL` is ignored as an input. SDK construction uses a serialized target/credential snapshot and restores ambient variables. The upstream `COMFYUI_URL` belongs to the proxy command, not app configuration. `.env` files are not automatically loaded by the scripts. Never embed keys in URLs or publish authenticated logs.

## Manual runtime evidence (optional, separate)

Only run inference with the operator's approval and suitable licensed models/assets. Follow [local setup](docs/local-setup.md) for proxy startup, then use `bash scripts/run_app.sh` to start the app. The launcher binds to loopback by default; the app has no built-in authentication. Do not expose it or ComfyUI publicly as a testing shortcut.

`/health` proves process liveness; `/api/readiness` checks the configured runtime without submitting a render. Neither proves a graph completed. For runtime-affecting changes, separately record an actual official-SDK render, retrieved artifacts, hashes, media properties and capsule/replay checks. Add human visual review and real desktop/mobile browser QA where relevant. State what was mocked, what was measured and what remains unverified; do not label a local result Cloud-validated.

## Review and GPU-free handoff checklist

Keep reviewable phases separate: **contract and failing regression → implementation → generated exports/documentation → optional live validation**. Prefer focused commits per boundary; do not mix an unrelated refactor, environment change or format migration into a bug fix. Before opening a pull request:

- [ ] Record the starting branch/revision, problem, intended behavior and explicit non-goals.
- [ ] Add a regression that fails for the original defect; cover invalid inputs, cleanup and historical formats where affected.
- [ ] Run the focused checks, then the isolated CPU suite; list exact commands, failures and skips. Run Node harnesses explicitly for browser-code changes.
- [ ] Regenerate only affected generated graphs; review schema, dependency and compatibility changes. Do not silently update vendor digests or historical fixtures to make tests pass.
- [ ] Review `git status --short`, `git diff` and `git diff --check` for accidental artifacts, secrets and unrelated work.
- [ ] Leave a concise handoff: changed boundaries, tests verified, known limits, outstanding manual/GPU/browser checks, and the next concrete task. A contributor without hardware should be able to resume from that record.
