# Open Jutsu Studio Roadmap

The direction stays simple: **Create → Swap → Continue → Share**, with reliable
saved work and less friction between studios. These are upcoming milestones,
not promises of features already delivered. Completion requires a tested user journey.

## Current preview

Characters, two Swap studios, vertical comparison Reels and experimental H3
native-take continuation are available. ComfyUI, nodes and weights are prepared
separately. A new H3 creation now captures its complete MP4, MCTX and COND family
in the same sampling job, and the Timeline composer opens that saved state
directly; native LTX continuation is not delivered.

## Next — trust what you save

- **One captured state per creation.** The family is published with the video, so
  a result cannot be reported as done while its native files are missing. Report
  unavailable capture capabilities before a costly run.
- **Version-compatible Character Save.** Reproduce and repair the development-only
  V8 recipe/save conflict before promoting that experiment. This is not a claim
  that Save is broken across the stable release. Preserve earlier Capsules,
  images and captions; verify named references after reload and restart.
- **Optional accelerated sampling.** Investigate an opt-in 8-step turbo mode with
  a compatible adapter, measured against the current 20-step path on the same
  parent, references, prompt, seed, duration and soundtrack. Keep today's verified
  mode available; adopt the faster one only if the comparison holds and the
  licences allow it. Faster sampling is not a quality claim.
- **Two clear outputs.** A lightweight social Reel for sharing, and a complete
  private native backup for reopening. Neither a recipe nor a public receipt
  substitutes for the native state.

## Then — connect the creative loop

- Make existing **Characters → Swap** reference handoffs easier to discover and
  verify the selected image, project and desktop/mobile reuse. Improve existing
  library/picker navigation rather than inventing a replacement backend.
- Validate the full library → selection → generation → reopen journey, including
  project boundaries and explicit selections without accidental generation.
- Ship a small, licensed **portable example** and engine-scoped provisioning
  guidance. Extend explicit, opt-in automation only after testing its nodes,
  weights, permissions and failure recovery on a clean executor.
- Add an **optional Docker app/proxy** path with a tested build, persistent data
  and restart/recovery instructions. No Docker installation is supplied today;
  a container alone will not provision every GPU dependency.

## Further — expand what we can prove

Improve native continuation, sound continuity and cross-target portability with
engine-specific acceptance. Extend Timeline operations only where their engines
support them. Strengthen install testing and regression coverage as the project
continues beyond the competition.

H3 MCTX/COND is not interchangeable with LTX or image-model state. Capabilities
will be documented per engine, not inferred from a shared interface.

## Contribute

Include version/commit, steps, expected and actual results, and sanitized
diagnostics. Do not attach API keys or private native backups to public reports.
See [setup](docs/local-setup.md), [documentation](docs/README.md) and
[contribution guidelines](CONTRIBUTING.md).
