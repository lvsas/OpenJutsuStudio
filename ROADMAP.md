# Open Jutsu Studio Roadmap

Four gestures: **Create**, **Swap**, **Continue**, **Share**. Everything below makes
one of them easier, faster or more reliable — never a feature for its own sake.

## What comes next, in order

1. **Install in one command.** It is three today (`make setup`, `make check`,
   `make run`) and a container for people who prefer that. Next: `make check` should
   be able to fix what it reports, and a Comfy Cloud path should exist for people
   without a GPU.
2. **Pick a person, not a description** — click someone in the frame and let SAM 3.1
   follow them. The tracking trial already followed two people across 240 frames; it
   has to become a button.
3. **Our own swap model** — trained on our footage, published with the comparison
   that shows what it changes.
4. **One library** — the same character in Create, Swap and Continue, backed by a
   small transactional store instead of loose files.

## Create — your characters, everywhere

- Your characters appear in the Timeline picker, not behind a file browser. Adding a
  reference is the same gesture in every workspace: pick from your gallery first,
  fall back to a file only when the character is new.
- One character, one identity: the same face, the same name, the same references
  wherever it is used, with a visible warning when a reference no longer matches.
- A character sheet you can share: a few poses, a few expressions, one link.
- The four character files stay declared and installable, gated ones included, so
  Create never fails because a weight was missing.

## Swap — put them in real footage

- **Click to select.** One click on the performer, SAM 3.1 follows them for the clip;
  the mask becomes the swap region, and you see where tracking was lost instead of
  discovering it in the result.
- **Our own model.** A swap adapter trained on our footage, with the licence, the data
  provenance and the A/B comparison published alongside it.
- **A faster mode.** Eight steps with a turbo adapter, as an option, without touching
  the quality of the current path.
- **Trust the take.** A short verdict per take — did it still move like the
  performance it replaced — so you stop scrubbing timelines to find the good one.
- **Several people.** Two performers swapped in one pass, each with their own mask
  and their own reference.

## Continue — one story, several takes

- A continuation inherits the references, the sound and the line from its parent, and
  says so in the interface instead of leaving you to remember.
- The stitched result plays as one shot, not two clips with a seam.
- A take you cannot continue says why: which native file is missing, and what to do
  about it.
- Long jobs survive a restart: resumed, failed cleanly, or explicitly abandoned —
  never a row that pretends to run for days.

## Share — the reel that travels

- One reel, three shapes: vertical, square and wide, from the same take.
- Captions and credits as sidecar files, so a clip can be re-posted without a re-render.
- Exports that are ready to publish, with the provenance attached — and no automatic
  posting, no invented reach.
- Batch export of a whole project with a manifest, for editors who work elsewhere.

## Foundations — the debt that makes the rest possible

- **Keep the install honest.** Every step that fails should say why; `make check`
  names what is missing today, it could install it tomorrow.
- **One library store.** Characters, takes, projects and reels are files and JSON
  today: honest, inspectable, and how a broken reference goes unnoticed. A small
  transactional store behind the files fixes that without hiding anything.
- **One graph builder.** Two modules compile the H3 graphs and one is a superset of
  the other. Pick one, and shorten what it generates.
- **Fewer, sharper tests.** Merge the overlapping UI contracts into one per screen and
  keep the tests that describe behaviour a person can observe, not the exact wording
  of a sentence.
- **Keep the disk honest.** Takes, swaps and reels grow fast; show what is using space
  and make deleting a take a one-click decision.

H3 native state (MCTX/COND) is not interchangeable with LTX or image state. Every
engine advertises what it can do; nothing is inferred from a shared button.

## Contribute

Send the version, the steps, what you expected and what happened, with logs that
contain no keys and no private media. See [setup](docs/local-setup.md),
[documentation](docs/README.md) and [guidelines](CONTRIBUTING.md).
