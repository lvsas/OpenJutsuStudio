# Creative Studio UI architecture

OpenGenjutsu's web UI is a local-first Creative Studio, not a raw ComfyUI parameter form.

## User-facing workflow

1. Select a source video.
2. Write one **Edit brief**: name the person and the desired change in the same sentence.
3. Optionally provide one character reference. Reveal a second ordered reference only when two visible people need recasting; only then can optional mapping hints distinguish Reference 1 from Reference 2.
4. Generate at the current truthful Studio HD quality: approximately 0.9 megapixels at the source aspect ratio, with 16 Ripple inference steps.
5. Review the result, download the MP4, or copy a caption for a post.

The UI intentionally focuses on a **visible character target** in its first active mode. The Edit brief carries the complete human request in natural language. Ordered mapping hints exist only when the second reference is disclosed; they help the first-frame editor distinguish two people, but are neither a segmentation mask, object tracker, nor a guarantee that an occluded subject will be found. Hidden mapping inputs are disabled so a one-reference request stays simple.

## Public vs internal controls

The user controls the source media, one Edit brief, optional references, optional two-person mapping hints, seed and Ripple strength. The propagation prompt is a model-policy constant (`RIPPLE_PROMPT`) and remains server-owned. This keeps the main request human-readable while preserving the technical context required for a two-reference attempt.

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
