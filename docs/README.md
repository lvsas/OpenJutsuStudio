# Documentation index

**v0.1.0-alpha.1 · Development preview · [Apache-2.0 application code](../LICENSE)**

## Start, make, share

- [Install the app and proxy](local-setup.md).
- [Prepare the ComfyUI executor](executor-setup.md): custom nodes and weights are separate.
- [Dependencies and file roles](dependencies.md).
- [Creative loop](../README.md#the-creative-loop): Create → Swap → Continue → Share.
- [Roadmap](../ROADMAP.md), [contributing](../CONTRIBUTING.md) and [component licences](model-licences.md).

## What to try

Bring a reference or use Characters' **18 wardrobe** choices and optional face
refinement. Select a short source shot in a Swap studio. For a continuable H3 take,
enable **Save native state too before generating**, then open it in Timeline.

The native Capsule connects the video, MCTX context, COND conditioning, references
and lineage. The upstream engine defines these formats; H3 and LTX states are
**not interchangeable**. Recipe JSON is not a replacement for native files.
The [standalone pack](../custom_nodes/opengenjutsu_continuity/README.md) explains
publication and restaging through the official SDK.

Download a vertical Reel from a completed Swap. Browser file sharing is optional;
download is the fallback. Copying a caption **does not upload the video**.
A social Reel is **not a complete Take backup**.

## Acceptance boundaries

Native capture is opt-in, not retroactive. Native H3 forward is experimental;
complete chain acceptance means **root → child → grandchild**, not one saved file.
Advanced **Before**, **bridge** and **refine** paths, **native LTX** continuation
and live **Cloud** execution retain separate acceptance gates. Inventory is not a
render or an artistic quality guarantee.

| Evidence | What it establishes | What it does not establish |
|---|---|---|
| **CPU** | Tested input, persistence, graph and file contracts. | GPU execution. |
| **Browser** | The served interactions actually exercised. | Every device or restored project. |
| **GPU** | A particular graph produced verified files. | Universal quality or target compatibility. |
| **Human** | Approval of a particular result/presentation. | Rights to unrelated media. |

Opening a workspace must not start inference; generation remains explicit.
