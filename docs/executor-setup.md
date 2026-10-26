# Prepare a ComfyUI executor for the two Swaps

This guide prepares a **self-hosted GPU executor**, local or remote. It does not
provision a paid GPU, deploy Comfy Cloud, install on app startup, or prove that a
new image can render. The app keeps using the official SDK and its self-hosted
proxy. Use a private/authenticated network; do not expose raw ComfyUI publicly.

## 1. Separate the environments

- Install ComfyUI with the NVIDIA/PyTorch/CUDA environment appropriate to the GPU.
- Use **the executor's Python**, not the application's `.venv`, for node requirements.
- Install FFmpeg on the executor as well as on the app host.
- The reference executor reports ComfyUI **0.42.0**. This is a checked reference,
  not a measured minimum-version guarantee. The actual node-class check below is
  the acceptance gate, including MiniMax H3 core nodes for H3.
- New GPU images must separately validate attention/quantization kernels. The LTX
  graph uses SageAttention patches; installing a node's `requirements.txt` alone
  does not ensure a compatible `sageattention` CUDA build. H3 uses Comfy kitchen
  attention and its selected quantized encoder. Do not silently substitute a
  different model/precision when a kernel or loader is unavailable.

## 2. Install only the needed custom node packs

`dependencies.json` is the source of truth for node classes, repositories and
installation revisions. The scoped checker uses the **real graph builders**,
not the union of old experiments and Characters templates.

| Pack | LTX Swap | H3 Swap | Optional H3 descriptions | Source selection |
|---|---|---|---|---|
| ComfyUI-VideoHelperSuite | yes | yes | | registry 1.7.9 |
| ComfyUI-LTXVideo | yes | | | `44c8a36b7c31ee00b4271daed11dc2a4aa481140` |
| ComfyUI-KJNodes | yes | | yes | `f20bdd5337ace70abbec147bdb68ea345d340836` |
| RES4LYF | yes | | | `56e44755d866c87ff9cb4b6608c8e42155db6ecc` |
| MiniMax H3 latent upscaler | | yes | | `40316cf008b2fd8663263270669eb4da23f89d2c` |
| ComfyUI-QwenVL | | | yes | `1b67b443918801f571714bab636edc1845b7002a` |

Install VHS **1.7.9 through ComfyUI Manager's version selection**. The manifest
also records its registry archive URL and the measured SHA-256 of that archive;
this is not a claim about the active Python process's bytes. A disabled nightly
checkout is not the active registry release and was not used as its provenance.

For the Git packs, clone the manifest's `source` into a **new** executor
`custom_nodes/<pack-name>` directory and check out `install.revision`. Example
for a fresh QwenVL install, with paths adapted to your executor:

```bash
COMFY_ROOT=/path/to/ComfyUI
COMFY_PYTHON="$COMFY_ROOT/.venv/bin/python"
# Only for an absent destination; never reset/replace an existing installation.
test ! -e "$COMFY_ROOT/custom_nodes/ComfyUI-QwenVL" && \
  git clone https://github.com/1038lab/ComfyUI-QwenVL "$COMFY_ROOT/custom_nodes/ComfyUI-QwenVL" && \
  git -C "$COMFY_ROOT/custom_nodes/ComfyUI-QwenVL" checkout --detach 1b67b443918801f571714bab636edc1845b7002a
# Review requirements against the prepared GPU environment before explicitly installing.
test "$(git -C "$COMFY_ROOT/custom_nodes/ComfyUI-QwenVL" rev-parse HEAD)" = 1b67b443918801f571714bab636edc1845b7002a &&   "$COMFY_PYTHON" -m pip install -r "$COMFY_ROOT/custom_nodes/ComfyUI-QwenVL/requirements.txt"
```

Repeat the same source/revision procedure for the other selected Git packs and
their requirement files when supplied. Preserve existing installations; do not
reset or overwrite them to force a match. Upstream source exports were inspected
at the declared revisions, **not imported together in a new GPU environment**.
Some reference classes resolve through a bundled local folder: install standalone
KJNodes/RES4LYF, not that bundle. The capsules and OBVPM packs are separate native
continuity prerequisites, not prerequisites of either baseline Swap renderer.

## 3. Install the fixed Swap weight files

Use the [explicit model installer](local-setup.md#prepare-fixed-swap-weights) on
the executor. `--engine ltx` includes FLUX first-frame editing; `--engine h3` does
not require LTX or Characters. The installer's declared defaults are not aliases
from the app's private Settings. Run the app's Settings → Test as well when using
custom filename mappings. Gated FLUX access is handled by your authorized account;
no agreement, token or weight is bundled in Git.

## 4. Preload optional H3 visual descriptions

The current source/reference-description path uses **Qwen3-VL-2B-Instruct with
4-bit quantization**, not a 4B checkpoint. This is separate from the H3 sampler's
text encoder and from the Characters generator's encoder. Runtime defaults have
not been changed. Failure remains a warning, not an implicit replacement model.

The inspected QwenVL node resolves `Qwen/Qwen3-VL-2B-Instruct` under
`models/LLM/Qwen/Qwen3-VL-2B-Instruct`. It can download missing files during an
**explicit description job**, not app navigation. To avoid a first-job download,
preload the pinned snapshot into a new, empty destination on the executor:

```bash
# Requires Hugging Face CLI in the prepared executor environment; no token in arguments.
# Stop and inspect if this directory already exists; do not replace its contents.
test ! -e "$COMFY_ROOT/models/LLM/Qwen/Qwen3-VL-2B-Instruct" && \
  hf download Qwen/Qwen3-VL-2B-Instruct \
    --revision 89644892e4d85e24eaac8bacfd4f463576704203 \
    --local-dir "$COMFY_ROOT/models/LLM/Qwen/Qwen3-VL-2B-Instruct"
```

Upstream snapshot metadata declares 4,266,648,961 bytes. The node needs a compatible
`transformers` version supporting Qwen3-VL (at least4.57.0), `bitsandbytes` for the
chosen quantization, `accelerate`, and its other declared requirements. Check CUDA
compatibility on the target. Do not install a GGUF server or switch encoder family
as a workaround. No vision weights were downloaded to validate this guide.

## 5. Check actual inventory without rendering

Restart your own executor only when its queue is idle, then from the app checkout:

```bash
env -u PYTHONPATH .venv/bin/python scripts/check_dependencies.py --host http://127.0.0.1:8188 --engine h3
env -u PYTHONPATH .venv/bin/python scripts/check_dependencies.py --host http://127.0.0.1:8188 --engine ltx
# Optional H3 description-node/model/quantization choices:
env -u PYTHONPATH .venv/bin/python scripts/check_dependencies.py --host http://127.0.0.1:8188 --engine all --with-descriptions --json
```

Use the executor's trusted URL, not the SDK proxy URL. `--object-info inventory.json`
reads an already saved `/object_info` response with **no network requests**; the
JSON report labels this as `snapshot`, not live. Unknown loader schemas fail closed
and are distinct from an explicitly empty file list. No generation is submitted.

Node/loader choices **do not prove** HF snapshot files exist, installed source
bytes match a revision, CUDA kernels load, or a render will succeed. Finish with a
bounded explicit render and read back its result on the authorized target. The
legacy checker without `--engine` still covers the broad manifest; its advanced
`--feature` selection is separate from these Swap scopes.
