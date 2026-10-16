# Creative Studio UI architecture

OpenGenjutsu's web UI is a local-first Creative Studio, not a raw ComfyUI parameter form.

## User-facing workflow

1. Select a source video.
2. Optionally provide a character reference image.
3. Identify the visible target when useful and describe the transformation.
4. Generate at the current truthful Studio HD quality: approximately 0.9 megapixels at the source aspect ratio, with 16 Ripple inference steps.
5. Review the result, download the MP4, or copy a caption for a post.

The UI intentionally says **visible target**. A text target description guides the first-frame editor; it is not a segmentation mask, object tracker, or guarantee that an occluded subject will be found.

## Public vs internal controls

The user controls the source media, reference, target description, edit instruction, seed and Ripple strength. The propagation prompt is a model-policy constant (`RIPPLE_PROMPT`) and remains server-owned. This prevents accidental prompt corruption and keeps the primary workflow understandable.

## Visual architecture

- `templates/index.html`: semantic studio structure, including recipe panel and preview stage.
- `static/design-system.css`: engine-scoped tokens and reusable primitives.
- `static/app.css`: responsive two-pane layout and stage-specific presentation.
- `static/app.js`: local preview state, readiness, job polling, human-readable stages, download and caption copy.

The root carries `data-engine="ltx"`. LTX uses lime accent tokens. A corresponding `[data-engine="h3"]` token block exists for a future MiniMax H3 experience, but H3 remains disabled in the interface until its backend is implemented, readiness-checked and proven by an end-to-end run.

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
- LTX active / H3 disabled, not falsely selectable.
- Source preview shows filename, duration and resolution after a real file selection.
- Generate unlocks only when readiness, source video and edit direction are present.
- Result actions remain hidden until the job is `done`.
- The two panes collapse cleanly to one column on mobile.
