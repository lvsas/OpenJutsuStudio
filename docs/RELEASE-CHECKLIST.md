# Release checklist

Every line is a command, not a memory. Run them in order from a clean checkout.

## 1. The tree is what you think it is

```bash
git status --porcelain      # expected: empty
git rev-parse --short HEAD   # note this commit
git ls-remote --heads origin # expected: one line, refs/heads/main
```

## 2. Nothing private is reachable

```bash
make privacy
# expected: three sections, each ending "clean", exit 0
```

The audit checks the working tree, every object reachable from `origin/*`, and each
remote ref. Add `AUDIT_INCLUDE_LOCAL=1` to also inspect local branches, which are not
published but may hold old paths. The exceptions live in `docs/audit-allowlist.txt`,
one `path|pattern|reason` per line, and each one is reviewed.

## 3. Authors and branches

```bash
git log --format='%an <%ae>' origin/main | sort -u
# expected: lvsas <lvsas@users.noreply.github.com> only
```

## 4. Tests and the release archive

```bash
make test
# expected: OK (skipped=1)
```

Then the release checkpoint, which builds a clean checkout and an archive of the
same tree and runs the suite in both:

```bash
python <artifacts>/verify-review-release.py
# expected: two JSON receipts with "passed": true
```

## 5. A machine can install it

```bash
make setup COMFYUI=/path/to/ComfyUI
make check             # expected: exit 0 when the executor is complete
python scripts/validate_install.py --comfyui /path/to/ComfyUI
# expected: ok lines, exit 0
```

## 6. The studio starts

```bash
make run                                     # host install
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/health   # expected: 200
```

## 7. Media in the repository

Only `docs/readme/` ships images: the demo GIF (2.3 MB) and interface captures.
No video, no model weights, no take is tracked. Verify:

```bash
git ls-files -s | awk '$1 != "100644" {print}'   # symlinks/modes that need a look
git ls-files | grep -E '\.(mp4|safetensors|sft|ckpt)$'   # expected: empty
```

## 8. Before publishing

- [ ] the demo clip contains no person who has not consented
- [ ] screenshots show no desktop, no browser tabs, no mailbox
- [ ] `LICENSE`, `NOTICE` and `docs/model-licences.md` match what ships
- [ ] the roadmap names work, not promises
- [ ] the repository becomes public only after every box above is ticked
