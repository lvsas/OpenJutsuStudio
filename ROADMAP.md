# Open Jutsu Studio Roadmap

The direction stays simple: **Create → Swap → Continue → Share**, with saved work
that can actually be reopened. This file is the work list, not a feature list:
everything below is either a defect we know about, a robustness gap, or debt we
created and have to pay back.

Nothing here is promised as delivered. A line leaves this file only when a test
proves it.

## 1 — Correctness and robustness

- **Install in one command.** `uv sync` gets the app, but the executor still needs
  a prepared ComfyUI with nodes and weights. Ship `scripts/install.sh` that checks
  Python 3.12, FFmpeg, reachability of the executor, every required node class and
  every model filename, then prints the exact missing items. A judge should not
  discover a missing node at submission time.
- **Fail before the GPU, not after.** Keep extending the preflight: model hashes,
  parent capsule, duration grid, reference count, audio policy. No job may start
  when its own inputs cannot satisfy it.
- **Crash recovery.** Every long operation must survive a restart: resumed,
  marked failed, or explicitly abandoned. One stale `running` job already sat in
  the queue for nine days.
- **Storage discipline.** Deletion, quotas and free-space checks on Takes, Swap
  media, reels and job records. The app is expected to run for months on a small
  disk; today it can fill it silently.
- **Error surfaces.** Every refusal carries an actionable sentence and a status
  code the UI can render. No bare `500`, no silent no-op.

## 2 — Debt we created

- **Two H3 graph builders.** `h3_continuity_graphs.py` compiles the native take,
  `h3_latent_graphs.py` the continuation, and the second is a superset of the
  first. Decide whether the take path should delegate to the latent builder
  instead of maintaining two topologies that can drift.
- **One HTTP client.** ComfyUI is reached through more than one path today; fold
  them into a single client with timeouts, retries and one place to log.
- **Serve the studio, not a copy.** Every static asset, template and demo page
  must have exactly one source of truth.
- **Repository size.** Drop tracked build artefacts and keep screenshots to what
  the README actually shows.
- **Naming.** `h3_continuity_graphs` builds takes, not continuity. Rename when the
  two builders are reconciled, not before.

## 3 — Person selection (SAM 3.1)

- The isolated trial worked: SAM 3.1 multiplex tracked **two people across 240
  frames**, with per-object masks and CPU overlays (`artifacts/…/sam-trial-20261027`).
- Integrate it as **click-to-select**: the user clicks a person on one frame, SAM
  tracks that person for the window, and the mask becomes the swap region.
- Do not use `SAM3Propagate` from the current node pack: it fails with a
  `cuda:0`/`cpu` tensor mismatch on this install, both with `video` and with
  `video_frames`. The working path is the `sam3.1_multiplex_fp16` checkpoint graph.
- Acceptance: mask covers the performer, excludes the microphone and the second
  performer, no drift across the window, and a visible preview of where tracking
  was lost.

## 4 — Our own LoRA

- Train a swap LoRA on our own footage instead of relying on the stock adapter,
  following the same recipe as the reference entries: fixed seed, fixed
  references, A/B against the current path on identical inputs.
- Publish the licence, the training data provenance and the evaluation protocol.
  A LoRA without a measured comparison is marketing, not engineering.
- Keep the 20-step path available; adopt a faster adapter only if the comparison
  holds and the licence allows commercial use.

## 5 — Custom node

- We depend on node packs we do not own. Identify the nodes whose behaviour we
  rely on and either pin their versions or vendor the small ones.
- If a node must be patched (latent upscaler dropping `noise_mask` is the known
  case), keep the patch in our repository with a test that fails when upstream
  changes, rather than editing a shared install by hand.

## 6 — Export and sharing

- **More than one reel format.** Today a single vertical Reel is produced. Add
  square and landscape variants with the same provenance.
- **Captions and credits** as sidecar files, so a shared clip can be re-published
  without re-rendering.
- **Direct handoff** to the platforms the user already uses, keeping the current
  rule: no automatic publishing, no invented reach.
- **Batch export** of a project's takes with a manifest, for editors who work
  outside the app.

## 7 — Presentation and proof

- Keep the demonstration film in step with the product: any visible change
  forces a re-capture, not a re-narration over stale footage.
- Publish the measured claims (tests, durations, refusal cases) with the release,
  not only in commit messages.

H3 MCTX/COND is not interchangeable with LTX or image-model state. Capabilities
are documented per engine, never inferred from a shared interface.

## Contribute

Include version/commit, steps, expected and actual results, and sanitized
diagnostics. Do not attach API keys or private native backups to public reports.
See [setup](docs/local-setup.md), [documentation](docs/README.md) and
[contribution guidelines](CONTRIBUTING.md).
