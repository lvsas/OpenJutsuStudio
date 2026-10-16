# Creative Studio UI architecture

OpenGenjutsu's web UI is a local-first Creative Studio, not a raw ComfyUI parameter form.

## User-facing workflow

1. Select a source video.
2. Optionally provide one character reference. Reveal a second ordered reference only when two visible people need recasting; its optional target hint stays separate from the global target description.
3. Identify the visible target when useful and describe the transformation.
4. Generate at the current truthful Studio HD quality: approximately 0.9 megapixels at the source aspect ratio, with 16 Ripple inference steps.
5. Review the result, download the MP4, or copy a caption for a post.

The UI intentionally focuses on a **visible character target**. A text target description and ordered reference hints guide the first-frame editor; neither is a segmentation mask, object tracker, or guarantee that an occluded subject will be found. The second reference is progressive disclosure, not a requirement: hidden secondary inputs are disabled so a one-reference request remains a one-reference multipart payload.

## Public vs internal controls

The user controls the source media, reference, target description, edit instruction, seed and Ripple strength. The propagation prompt is a model-policy constant (`RIPPLE_PROMPT`) and remains server-owned. This prevents accidental prompt corruption and keeps the primary workflow understandable.

## Visual architecture

- `templates/index.html`: semantic studio structure, including recipe panel and preview stage.
- `static/design-system.css`: engine-scoped tokens and reusable primitives.
- `static/app.css`: responsive two-pane layout and stage-specific presentation.
- `static/app.js`: source preview, readiness, job polling, human-readable stages, download and caption copy.
- `static/reference-controls.js`: progressive second-reference disclosure, independent thumbnails and object-URL cleanup.
- `static/studio-utils.js`: shared toast, source-preview URL and duration helpers.

The root carries `data-engine="ltx"`. LTX is the only public engine identity. The disabled `More Soon` chip is deliberately engine-neutral: it signals future studio modes without advertising, comparing with, or implying support for an unimplemented model.

## Export and sharing

The local studio can download a completed MP4 and copy a caption. It does **not** claim public social sharing: a local result URL cannot be opened by an external recipient.

A future hosted artifact API may add `public_result_url`. The acceptance test is end-to-end: a recipient without access to the creator's LAN opens the exact shared result. Until then, no X/LinkedIn share button may imply that the result is externally available.

## Browser validation

For every UI change, verify:

```bash
node --check src/static/app.js
env -u PYTHONPATH .venv/bin/python -m unittest discover -s tests -v
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/api/readiness
```

Then check desktop and mobile in a browser:

- English-only text and no visible propagation prompt.
- LTX active / neutral `More Soon` teaser disabled and not falsely selectable.
- Source preview shows filename, duration and resolution after a real file selection.
- Generate unlocks only when readiness, source video and edit direction are present.
- One reference is compact by default; target hints stay collapsed; the second reference appears only after explicit disclosure.
- With two fixture files selected, submitted `reference_images` and `reference_targets` preserve browser order; removing the second leaves only the primary binding.
- Result actions remain hidden until the job is `done`.
- The two panes collapse cleanly to one column on mobile.
