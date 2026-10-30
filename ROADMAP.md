# Open Jutsu Studio Roadmap

**Create → Swap → Continue → Share.** That is the whole product. Everything below
either makes one of those steps work better or gets out of its way.

No dates, no promises. A line leaves this page when it is done and tested.

## Now — make it solid

- **Install anywhere.** One command on Linux, macOS and Windows that tells you what
  is missing instead of failing halfway.
- **Never fail at the last second.** Check the inputs before the GPU starts: the
  take, the references, the sound, the durations.
- **Survive a restart.** A long job interrupted by a reboot must resume, fail
  cleanly, or say so — never sit there pretending to run.
- **Keep the disk honest.** Takes, swaps and reels grow fast. Show what is using
  space, and make deleting a take a one-click decision.

## Next — make it feel right

- **Pick a person, not a description.** Click someone in the frame and let SAM 3.1
  follow them through the clip. The trial tracked two people over 240 frames; it
  needs to become a button.
- **Trust the take.** A short, honest verdict per take — does it still move like the
  performance it replaced — so you stop scrubbing timelines to find the good one.
- **Our own swap model.** Train the adapter on our own footage, and publish the
  comparison, the licence and the provenance with it.
- **A faster mode.** Eight steps with a turbo adapter, as an option, without
  touching the quality of the current path.

## Later — make it spread

- **One reel, three shapes.** Vertical, square and wide, from the same take, with
  captions and credits as sidecar files.
- **Hand off, do not publish for people.** Exports that are ready to post, with the
  provenance attached.
- **Batch export** of a whole project with a manifest, for editors who work elsewhere.

## Under the hood — debt we owe

- Two builders compile the H3 graphs; one is a superset of the other. Pick one.
- One HTTP client for the executor, with timeouts and retries in a single place.
- A shorter take graph: it is generated, and it shows.
- Ship a container, so nobody has to assemble a ComfyUI by hand.

H3 native state (MCTX/COND) is not interchangeable with LTX or image state. Every
engine advertises what it can do; nothing is inferred from a shared button.

## Contribute

Send the version, the steps, what you expected and what happened, with logs that
contain no keys and no private media. See [setup](docs/local-setup.md),
[documentation](docs/README.md) and [guidelines](CONTRIBUTING.md).
