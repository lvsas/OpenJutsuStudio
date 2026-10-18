# Workflow files

These are the API-format graphs this app submits, exported by
`scripts/export_workflows.py`. Regenerate them after any change to a graph builder:

```bash
env -u PYTHONPATH .venv/bin/python scripts/export_workflows.py
```

| File | Engine | Nodes |
| --- | --- | --- |
| `ltx-frame-edit.api.json` | FLUX 2 Klein 9B image edit — the first-frame anchor | 22 |
| `ltx-ripple.api.json` | LTX 2.5 + Ripple FFAF IC-LoRA — the motion pass | 30 |
| `h3-recast.api.json` | MiniMax H3 two-pass character swap — the H3 Studio take | 26 |

## Why they are exported rather than hand-edited

This project builds its graphs in code (`src/graphs.py`, `src/h3_graphs.py`) so they stay
testable, pinned to the frozen take recipe, and free of the hand-edit drift that makes a
saved workflow and a running app disagree. The exported files are the same graphs, written
out so the workflows ship with the repository and can be read or loaded in API format.

`h3-recast.api.json` is exported exactly as it is frozen for a take — same canvases, same
frame grid, same audio conditioning — so what ships here is what runs.

## Placeholders

Every asset is a named placeholder, and the app substitutes a real asset for each before
submitting:

| Placeholder | Replaced with |
| --- | --- |
| `og-source-frame-placeholder.png` | the reference frame the anchor is built from |
| `og-character-reference-placeholder.png` | the uploaded character reference |
| `og-source-video-placeholder.mp4` | the normalised, padded source clip |
| `og-edited-frame-placeholder.png` | the anchor returned by the image-edit stage |
| `h3-source-placeholder`, `h3-reference-placeholder-<n>` | the prepared H3 source and each uploaded character reference, in order |

## Loading them

They are **API-format** graphs, not UI-format workflow files. Submit them to a ComfyUI
`/prompt` endpoint, or convert them for the canvas. They carry no credentials and no local
paths: the model filenames they reference must be installed on the target ComfyUI, and
`README.md` lists them.
