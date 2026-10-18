# Documentation index

Start with the [project README](../README.md) — what the product does, the two studios,
how to run it and how each competition requirement is met. This page is the map of everything
under `docs/`.

**Reading convention.** Files dated `2026-10-15` and `2026-10-16` are the record of how the
product got here: measurements, rejected approaches and superseded plans. They are kept because
a claim without its failed attempts is not evidence. Files dated `2026-10-17` and later describe
what the product **is now**. Where an older file contradicts a newer one, the newer one wins.

---

## Start here

| Document | What it answers |
| --- | --- |
| [Local setup](local-setup.md) | how to run this on your own machine: Python 3.12, FFmpeg, the SDK proxy, a remote upstream, and the usual failures |
| [Creative Studio UI architecture](ui-architecture.md) | how the interface is organised, why the two studios share one language, and where local sharing stops |
| [Open Weights runtime contract](validation/open-weights-runtime-contract.md) | which models, nodes and transport are declared, and what "ready" actually verifies |
| [Competition roadmap](plans/competition-roadmap.md) | the requirements checklist, what is done, and what is still open |

## Current — what the product is

| Document | What is in it |
| --- | --- |
| [H3 Studio runtime validation](validation/h3-studio-runtime.md) | the isolated two-pass runtime: what was rendered, at which size, with what result |
| [H3 prompt-wording A/B](validation/h3-prompt-wording-ab.md) | the measured verdict on what makes an H3 take good: naming what must be preserved, not the phrasing |
| [Automatic description](validation/h3-auto-description-probe.md) | how the studio writes the descriptions itself from the clip and each reference image, and what the model is forbidden to invent |
| [H3 multi-reference plan](plans/h3-multi-reference-phase3.md) | the ordered steps that gave H3 two character references |
| [H3/LTX UX parity plan](plans/2026-10-17-h3-ltx-ux-parity.md) | the atomic plan behind the interface work, phase by phase |
| [Product reflection](plans/product-reflection-three-modes.md) | where the character creator and the timeline editor belong, and what makes the three modes one product |
| [Post-MVP roadmap](plans/2026-10-18-post-mvp-roadmap.md) | the three-step product, the order of work, and the risks it accepts |
| [Viral Character plan](plans/2026-10-18-viral-character-phase.md) | the character module, task by task: trend library, recipe, graph, capsule, page |
| [Timeline plan](plans/2026-10-18-timeline-latent-phase.md) | extend, prepend and bridge from the latent capsules, with the pack's traps as test assertions |
| [Dependencies](dependencies.md) | every node class and model file this repository needs, verified against a live ComfyUI |
| [H3 license gate](validation/h3-license-gate.md) | contest eligibility is not a commercial or territorial licence — read before deploying or sharing output |
| [Prompt profiles](architecture/prompt-profiles.md) | how a prompt policy is versioned and frozen per engine |
| [H3 and the continuity capsule](architecture/h3-continuity-capsule.md) | the capsule is **live** in both studios; this records which H3 mechanisms that document proposed and we did not adopt |

## Evidence — what has been measured

| Document | Question it settled |
| --- | --- |
| [Single-subject identity baseline](validation/2026-10-17-single-subject-identity-baseline.md) | does a first-frame edit carry identity through motion |
| [Ripple strength A/B](validation/2026-10-17-ripple-strength-identity-ab.md) | what the strength control does to identity |
| [Cut segmentation A/B](validation/2026-10-17-ltx-cut-segmentation-ab.md) | what happens around a hard cut |
| [Licensed real-footage stress](validation/2026-10-17-licensed-real-motion-stress.md) | one real trailer, end to end |
| [Multi-reference GPU validation](validation/2026-10-16-ltx-multi-reference-gpu.md) | LTX with two character references |
| [H3 LoRA stock smoke](validation/2026-10-16-h3-stock-lora-smoke.md) | the Character Swap LoRA on an unmodified ComfyUI |
| [Reference-first recast](validation/reference-first-no-prompt.md) | that a reference alone is enough to start |
| [Qwen preflight](validation/qwen-local-preflight.md), [reference preflight](validation/qwen-reference-preflight.md) | what a local vision model could and could not be trusted with |
| [Robustness protocol](validation/robustness-protocol.md) | the acceptance protocol for general editing |
| [Local reliability](validation/local-reliability-2026-10-15.md) | the local-first reliability pass |

## Audits — what was wrong and what was done about it

| Document | Outcome |
| --- | --- |
| [H3/LTX UI gaps, deep pass](audits/h3-ltx-ui-gaps-deep-2026-10-17.md) | every measured interface difference and its cause; most are now fixed |
| [H3/LTX UI gaps](audits/h3-ltx-ui-gaps-2026-10-17.md) | the first pass, kept because it named the capsule colour and cache defects |
| [H3 preview and capsule review](audits/h3-preview-capsule-review-2026-10-17.md) | work that was rejected and reworked; the reasoning that produced the current interface |
| [UX parity audit](audits/h3-ltx-ux-parity-2026-10-17.md) | the original gap matrix |
| [Competition UX gap](audits/2026-10-16-competition-ux-gap.md) | what a judge would have found missing |
| [Genjutsu parity audit](audits/2026-10-16-genjutsu-parity-audit.md) | where this rebuild stands against the product it rebuilds |

## Plans that built what exists

Delivered, kept because they explain why the current architecture looks the way it does:

| Document | What it delivered |
| --- | --- |
| [H3 studio consolidation](plans/h3-studio-consolidation.md) | the two-studio architecture: the isolated H3 graph, the H3 runner and route, the frozen H3 recipe with source/reference/result lineage, and the H3 Capsule |
| [Creative studio UX](plans/2026-10-16-creative-studio-ux.md) | the studio interface as it stands (its own status: substantially implemented) |
| [Share reel](plans/2026-10-16-share-reel.md) | the local 1080×1920 before/after reel a creator downloads |
| [Multi-reference FLUX conditioning](plans/2026-10-16-multi-reference-object-swap.md) | the two-reference first-frame path, in use in LTX today |
| [Local reliability](plans/2026-10-15-local-reliability.md) | the local-first reliability pass |

## Earlier plans, superseded or not adopted

| Document | Why it is not the current plan |
| --- | --- |
| [Local app and competition plan](plans/2026-10-15-opengenjutsu-general-product-plan.md) | superseded by the [competition roadmap](plans/competition-roadmap.md) |
| [Reference intelligence](plans/2026-10-16-reference-intelligence.md) | the opt-in vision preflight it planned was measured and rejected; the measurements are in [Qwen preflight](validation/qwen-local-preflight.md) |

## Architecture brief

[Performance Recast Director](architecture/performance-recast-director.md) — the product brief.
