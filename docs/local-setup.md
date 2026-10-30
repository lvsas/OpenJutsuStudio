# Local setup (Gate A)

The supported local path is **Python 3.12 app → local Comfy SDK v2 proxy →
self-hosted ComfyUI**. The proxy translates the SDK API; the raw ComfyUI port is
not a replacement for that API. Cloud execution is not verified by this guide.

## 1. Prerequisites

- Git and either a Bash shell (Linux/macOS) or Python 3.12 (Windows: use `python scripts/launch.py`).
- [uv](https://docs.astral.sh/uv/getting-started/installation/) on `PATH`.
  Setup uses `uv venv .venv --python 3.12`. uv can download Python 3.12 if it is
  absent; network access to the configured Python/package sources is required.
- **FFmpeg**, with both `ffmpeg` and `ffprobe` on `PATH`. For example, on
  Debian/Ubuntu: `sudo apt-get install ffmpeg`; on macOS: `brew install ffmpeg`.
  Setup detects missing executables and stops before installing Python packages;
  it does not install system packages or run privileged commands itself.
- A running, reachable ComfyUI with the required custom nodes and model weights.
  See the [README requirements and model list](../README.md#requirements).
  ComfyUI, its Python environment and its GPU dependencies are managed separately.
  Weights and licenses are not bundled or automatically accepted by app setup.

Check the local tools:

```bash
uv --version
ffmpeg -version
ffprobe -version
```

## 2. Fresh checkout and environment

```bash
git clone https://github.com/lvsas/OpenJutsuStudio.git
cd OpenJutsuStudio
bash scripts/setup.sh
```

If repository access requires authentication, use your own authorized GitHub
account; this guide does not change repository visibility or contain credentials.

Setup creates a real, project-local `.venv` and `work/jobs` / `work/media`; it does
not depend on an environment at another checkout. It installs `requirements.txt`
using that interpreter, not the shell's `python` or `pip`. Setup and the app
launcher clear `PYTHONPATH` to avoid imports from an unrelated Python environment.
No activation is needed. Subsequent setup runs reuse a Python 3.12 environment.

**Proxy installation is separate and opt-in:**

```bash
bash scripts/setup.sh --with-proxy
# Options only; does not install anything:
bash scripts/setup.sh --help
```

The flag installs `comfy-api-proxy==0.1.6` into the same `.venv`, in addition to
app requirements. It never starts a proxy, app, GPU job, or model download.
Skip the flag if you already manage a compatible SDK v2 endpoint elsewhere.
Application dependencies use bounded ranges rather than a complete lockfile;
this bootstrap is not a byte-for-byte reproducible release build.

### Existing or shared environment

An existing environment with the wrong Python version, a broken `.venv` symlink,
or an unusable `.venv` produces an error instead of being overwritten. Setup
never removes an environment. Inspect it first:

```bash
ls -ld .venv
env -u PYTHONPATH .venv/bin/python --version
```

If you decide to replace it, move the `.venv` entry to a **new, unused** backup
name before rerunning setup. Moving a symlink moves only the link; do not delete
its shared target. Keep the old environment until the new one is validated.
`.gitignore` excludes `.venv` as either a directory or symlink, but cannot untrack
an entry already in Git's index; that must be handled separately by maintainers.

### Prepare fixed Swap weights

Run the model installer **on the ComfyUI executor host**, from this checkout,
after creating a ComfyUI installation with an existing `models/` directory:

```bash
# Read-only plan; --engine ltx includes its FLUX first-frame editor.
env -u PYTHONPATH .venv/bin/python scripts/download_models.py --comfyui /path/to/ComfyUI --engine all --dry-run
# Explicitly authorize downloads for just H3 (or choose ltx/all):
env -u PYTHONPATH .venv/bin/python scripts/download_models.py --comfyui /path/to/ComfyUI --engine h3 --download
```

Without `--download`, this only reads the local manifest. An incomplete manifest
fails instead of pretending to install a partial engine. The 15 fixed file roles
are mapped to exact loader filenames in `dependencies.json`, with pinned upstream
revision, size and published LFS SHA-256. No alternative precision/model is chosen.
The current complete set declares 102,968,476,145 bytes before vision models,
Characters, native continuity, Python/GPU environments or caches; plan disk space
on the executor, not the app host. Nothing downloads on app startup/navigation.

The FLUX Klein diffusion source requires upstream authorized access. Acquire that
exact pinned file with your own authorized account and put it at the planned
path before LTX/all installation. This CLI does not take credentials or accept
agreements for you; the app's Comfy endpoint key is not a Hugging Face credential.

Existing files are verified and skipped only if their Safetensors layout, size and
SHA-256 match; otherwise installation fails without replacing them. Symlink paths
are refused. Failed unique `.part` files are retained for inspection; successful
staging remains as a hardlink to the final file (same storage, not a second weight
copy). The script never deletes/replaces old weights or partials. It needs POSIX
filesystem support for no-follow directory traversal and atomic no-clobber links.

Custom nodes remain separate: install the selected profile's repositories and
revisions from `dependencies.json` in the executor's environment. The standalone
capsules and OBVPM packs are additional native-state prerequisites, not baseline
video-only Swap requirements. Vision-description HF folders may be acquired by
their upstream vision node and are **not** part of this fixed-file downloader.
Characters and native continuity likewise require their separate manifest roles.
Restart your own ComfyUI only when its work is idle, then check its actual node and
loader inventory; a successful weight download is not a proven GPU render.

See [executor setup](executor-setup.md) for the exact standalone custom-node
source/version selections, attention/quantization prerequisites and optional H3
vision snapshot preloading. The scoped check `--engine h3` does not require LTX,
Characters or experimental continuity packs. `--engine ltx` includes FLUX editing.
Use `--engine all --with-descriptions` to check both and optional vision choices;
HF snapshot file presence still needs executor-side verification.

## 3. Launch the proxy explicitly

Start ComfyUI with the required nodes and weights first. In terminal A, from this
checkout:

```bash
# This URL is the upstream ComfyUI server, not the app or SDK endpoint.
export COMFYUI_URL=http://127.0.0.1:8188
env -u PYTHONPATH .venv/bin/comfy-api-proxy run \
  --comfyui "$COMFYUI_URL" --host 127.0.0.1 --port 8189
```

For ComfyUI on another machine, replace the upstream **before running the same
proxy command**, for example:

```bash
export COMFYUI_URL=http://comfyui-host:8188
# Now run the proxy command above in this terminal.
```

`comfyui-host` is an example hostname: substitute your trusted server. Only the
proxy needs access to that upstream; model files remain installed on the ComfyUI
host. `COMFYUI_URL` is a shell variable passed explicitly to `--comfyui`; the app
does not use it and the proxy does not automatically read it. Restart the proxy
to change the upstream. Do not use a remote machine's filesystem path as a local
model-download destination.

The proxy stays in the foreground (Ctrl+C stops it). It binds only to loopback;
do not add an insecure bind or expose an unauthenticated ComfyUI service to the
Internet. Use a trusted network or an authenticated tunnel for remote upstreams.
No proxy token is needed for this loopback-only, single-user setup. An authenticated
or cloud endpoint requires separately configured credentials and validation.

## 4. Launch the app

In terminal B, from the same checkout:

```bash
# The launcher pins this local proxy unless an explicit application override is set.
bash scripts/run_app.sh
```

Before any saved configuration, the app uses `http://127.0.0.1:8189` unless
`OPENGENJUTSU_COMFY_BASE_URL` selects another API-v2 endpoint. Saved Settings take
precedence. Ambient `COMFY_BASE_URL` cannot silently select a Cloud target. The app binds to `127.0.0.1:8000`. Override the app port if necessary:

```bash
OPENGENJUTSU_PORT=8001 bash scripts/run_app.sh
```

Open <http://127.0.0.1:8000> (or your chosen app port). Stop the app with Ctrl+C.
The launcher does not start or stop ComfyUI/proxy processes. Environment variables
must be exported in the terminal starting the relevant process; `.env` files are
not automatically loaded by these shell scripts. Never commit credentials:
`.env` and `.env.*` are ignored, and no key is required for the default local path.

| Setting | Meaning | Local default |
| --- | --- | --- |
| `COMFYUI_URL` | Upstream passed to proxy `--comfyui` | `http://127.0.0.1:8188` in the example |
| `OPENGENJUTSU_COMFY_BASE_URL` | Bootstrap API-v2 target when no Settings are saved | `http://127.0.0.1:8189` |
| `OPENGENJUTSU_PORT` | App HTTP listen port | `8000` |

### Configure in the app

Open **Settings** in the shared header, or `/settings`. Enter the API-v2 URL and,
if required, its API key. The saved key is never read back into the browser; blank
keeps it only for an unchanged URL. Selecting a different URL does not forward the
old credential. **Test connection** checks the proposed target without saving,
uploading or generating. **Save settings** activates the configuration without a
restart, but refuses while submissions, queued workers or native work are active.
Revision conflicts keep your draft; no request is retried automatically.

The private `work/settings/compute.json` is excluded from Git, mode0600 inside a
0700 directory. Protect/back up it as server configuration, not a shareable asset.
Opening Settings only reads this configuration. Local/Cloud inventory checks can
list missing nodes/models; remote API-v2 connection with unavailable inventory is
reported **unknown**, not falsely ready or missing. Install the required files on
the actual ComfyUI host. Live Cloud acceptance is a separate gate; no automatic
model/node download or paid render occurs here.

Expand **Models** only when your compatible weights use different filenames.
The LTX and H3 groups identify each fixed loader/input role. Keep its default or
enter the exact compatible filename (including relative subfolders and case).
An explicit **Test connection** can supply suggestions from that loader's own
inventory; suggestions do not select weights or guarantee architecture, precision
or format compatibility. When inventory is unavailable, manual entry remains
possible and dependencies remain **unknown**. Opening the section does not probe.

**Save settings** stores these overrides with the selected target and revision.
Changing the URL clears the old target's aliases; changing only its key preserves
them. **Use default** and **Reset model overrides** change only the draft until
Save. New Swap recipes freeze their effective filenames. A replay checks and uses
its recorded files, not today's Settings; installing an alias does not migrate
past capsules or make missing historical files interchangeable. The experimental
native continuity profiles and optional vision-description model are separate
contracts, not automatically remapped by the Swap loader roles.

The manifest command-line checker describes the declared installation defaults
and supported alternatives. For your configured Swap aliases, **Test connection**
and the operation's graph-based preflight are the target-aware checks.

## 5. Verify without submitting a render

Setup does not install ComfyUI or its custom nodes. Settings keeps the API key
write-only; testing a connection does not submit generation. Check each selected
engine without inference (use your executor URL):

```bash
env -u PYTHONPATH .venv/bin/python scripts/check_dependencies.py --host http://127.0.0.1:8188 --engine h3
env -u PYTHONPATH .venv/bin/python scripts/check_dependencies.py --host http://127.0.0.1:8188 --engine ltx
```

With the services running, these are read-only checks (curl is optional tooling):

```bash
curl --fail --show-error --max-time 10 http://127.0.0.1:8189/api/v2/health
curl --fail --show-error --max-time 10 http://127.0.0.1:8000/health
curl --show-error --max-time 30 http://127.0.0.1:8000/api/readiness
```

`/health` is **process liveness only**. `/api/readiness` checks dependencies and
returns diagnostic JSON; a non-ready result must be resolved before job submission.
Proxy health alone does not establish that every graph node and model is available.
Readiness is not evidence that a full GPU edit completed or that quality is good.

Common failures:

- **`uv` missing:** install uv and ensure the invoking shell has it on `PATH`.
- **FFmpeg / ffprobe missing:** install the full FFmpeg package; retry setup.
- **Python version mismatch:** inspect/move the old `.venv` safely, then rerun setup.
- **`comfy-api-proxy` missing:** opt in using `bash scripts/setup.sh --with-proxy`.
- **Connection refused at 8189:** start the proxy, or set
  `OPENGENJUTSU_COMFY_BASE_URL` to the trusted self-hosted proxy URL.
- **Upstream unreachable:** verify the URL supplied via `COMFYUI_URL` and remote
  connectivity from the proxy host; changing the app URL will not fix this.
- **Missing nodes or models:** install the named prerequisites on the ComfyUI host,
  then restart ComfyUI when required and recheck readiness.
- **Port already in use:** do not stop someone else's service. Choose another
  proxy `--port` and set `OPENGENJUTSU_COMFY_BASE_URL`, or change
  `OPENGENJUTSU_PORT` for the app.

## 6. CPU-only regression checks

```bash
env -u PYTHONPATH .venv/bin/python -m unittest tests.test_setup -v
env -u PYTHONPATH .venv/bin/python -m unittest discover -s tests -v
bash -n scripts/setup.sh scripts/run_app.sh
git diff --check
```

The setup tests use isolated temporary trees and stub external tools. CPU media
tests generate their own small FFmpeg fixtures; they do not require a downloaded
clip outside this repository. Orchestration tests mock model calls and isolate
job files in temporary directories. These tests are not GPU or Cloud evidence.

Real clean installation must also be tested with the actual uv and package
sources. When exporting a working checkout for that smoke test, explicitly
**exclude `.venv`**
(including an absolute symlink), `.git`, local `.env*` files, generated `work/`
content and caches. Do not copy or dereference a shared environment into the test
checkout, and do not run setup against the original shared environment just to
test bootstrap. Passing setup/tests does not validate GPU execution, Cloud,
character-reference UX, model licensing, or contest readiness.
