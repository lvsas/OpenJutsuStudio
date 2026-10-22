# OpenGenjutsu Continuity (CPU file adapter)

Apache-2.0. A narrow interoperability adapter for an existing H3 MP4 +
`mctx_v1` + `obvpm_cond_v1` family. It does not generate media, restore tensors,
provide model weights, reconstruct missing state, or certify visual continuity.
It is not a new video model or a replacement for the upstream H3 timeline pack.

## Installation (manual approval required)

Install the standalone repository under the selected ComfyUI installation:

```bash
cd /path/to/ComfyUI/custom_nodes
git clone https://github.com/lvsas/ComfyUI-OpenJutsu-Capsules.git
```

For updates, run `git pull --ff-only` **inside that pack directory**, then restart
ComfyUI normally. The entrypoint is
`custom_nodes/ComfyUI-OpenJutsu-Capsules/__init__.py`, not a nested second copy.
The application's archive is a reproducible build artifact, not the update path.
Do not install the whole application repository as a node pack. Nothing
auto-installs dependencies or edits graphs.

Requirements: Linux with `renameat2(RENAME_NOREPLACE)`, local `/proc` mounted,
Python 3.10+, and `ffprobe` on the ComfyUI service's PATH. No pip, GPU, SDK,
torch, safetensors runtime or app requirements are needed by these nodes.
FFprobe is an external CPU dependency; install it through the host's normal
package-management process, not through this pack. Writable input/output roots
must be the native `folder_paths` directories. The staging parent is created
mode 0700; an existing parent must be owned by the service user and not writable
by group/others. Do not expose a shared hostile filesystem as a Comfy root.

Normal managed/developer-API workflow remains required: enable/use the target's
supported Comfy API v2 service (on self-hosted instances, the official proxy
must already target the intended Comfy instance), confirm authenticated node
inventory shows the required classes, upload all assets through that service, submit
API-format graphs through the official SDK, poll and retrieve the completed
job's node outputs. Installation in Manager or a successful restart alone is
not SDK or native-H3 roundtrip proof. This pack is not registered in Manager or
approved for Comfy Cloud; neither availability nor deployment is implied.

## Node contracts

All three nodes are terminal `OUTPUT_NODE=True`, function `execute`, category
`OpenGenjutsu/Continuity`. PublishFamily/RestageFamily take separate
`video`, `mctx`, `conditioning` STRING inputs; PublishClip takes the actual
native saver `clip` STRING. They return `(clip: STRING, manifest_json: STRING)` and actual
`ui.files` descriptors **on the same output node**, for example:

```json
{"ui":{"files":[
  {"filename":"take.mp4","subfolder":"opengenjutsu_continuity/example","type":"output"},
  {"filename":"take.mctx.safetensors","subfolder":"opengenjutsu_continuity/example","type":"output"},
  {"filename":"take.cond.safetensors","subfolder":"opengenjutsu_continuity/example","type":"output"}
]}}
```

The path-free JSON manifest holds exact SHA-256/byte sizes, formats, shared
video identity and delivered media geometry, not filenames, local paths or
credentials. Descriptor paths and the loader handle are separate intentional
output-relative references. Official proxy 0.1.6 maps `ui.files` to SDK output
type **file**, including the MP4. Consumers must identify roles by suffix, not
expect the MP4's normalized output type to be `video`.

### `OpenGenjutsuH3PublishFamily`

Inputs are three explicit paths beneath the configured output root. Confined
absolute paths are allowed; relative paths are preferred. No adjacency is
assumed: different stems and subfolders are valid. The node verifies all three
actual files and returns their real descriptors without copying them.
`clip` is returned only when both sidecars are actually adjacent with the
video radical; otherwise `clip` is the empty string, never a guessed handle.
Publish only stable, completed files; do not overwrite them after publication.

### `OpenGenjutsuH3PublishClip`

Wire the actual `H3TrimAndSaveVideoWithMCtx` clip STRING into `clip`. It accepts
the saver's absolute path only beneath the configured output root, or an exact
output-relative path. The two adjacent sidecars follow the verified stock
`mctx.sidecar_path` and `condstore.cond_path` conventions. Every file and its
shared identity is then validated by the same PublishFamily implementation.
Missing/corrupt state is an error. No counter guessing, directory scan or input
asset-name inference occurs. The returned handle is output-relative; capture
that output through SaveText for a subsequent loader job, not the stock saver's
absolute path. This closes graph publication wiring, not GPU or Cloud proof.

### `OpenGenjutsuH3RestageFamily`

The additional required `family_name` is a fresh caller-chosen identifier:
1-80 ASCII alphanumeric/underscore/hyphen characters, starting alphanumeric.
Each of the three asset-backed STRING inputs must be the **actual proxy-resolved
input-relative filename**, including its actual subfolder. Different names and
folders, including content-deduplicated upload locations, are supported.
Never derive the sidecars from the video upload's name. Do not pass an output
asset reference directly: proxy output references resolve to output-relative
names, whereas this node deliberately reads the input root. Download and
re-upload all three files first, using their genuine asset IDs.

An API-format input graph after SDK asset upload has this shape (placeholder
IDs must be replaced with the actual three uploaded asset IDs):

```json
{"17":{"class_type":"OpenGenjutsuH3RestageFamily","inputs":{
  "video":{"__type":"core/ASSET","info":{"id":"VIDEO_ASSET_ID"}},
  "mctx":{"__type":"core/ASSET","info":{"id":"MCTX_ASSET_ID"}},
  "conditioning":{"__type":"core/ASSET","info":{"id":"COND_ASSET_ID"}},
  "family_name":"example"
}}}
```

The node confines and validates the explicit input family, streams the exact
bytes into a private staging directory under output, revalidates the copied
family against all original hashes, fsyncs, and atomically publishes without
clobbering any existing file, symlink, empty or nonempty directory. There is no
check-then-replace fallback. Unsupported atomic publication fails closed.
It returns `opengenjutsu_continuity/example/take.mp4`; adjacent siblings are
exactly `take.mctx.safetensors` and `take.cond.safetensors`. Partial pre-publish
failures clean staging. Complete final directories are never deleted on errors.
Process death may leave a hidden `.stage-*` directory; inspect it manually when
no jobs are running. Final directories are immutable by convention, not ACLs.

## Validation and limits

No symlinks (including parent components), traversal, paths outside the configured
root, FIFOs, sockets or directories are accepted as files. Confined absolute
restager paths are supported. Portable filename components start alphanumeric
and contain ASCII letters/digits, `_`, `-`, `.`, spaces or parentheses, are at
most 200 characters and do not end in a dot or space.
The shared role-suffix policy accepts ComfyUI's numeric collision marker before
the final extension, such as `take.mctx (1).safetensors` and
`take.cond (1).safetensors`. Only the suffix comparison is normalized: the exact
supplied path is opened, hashed and copied. The SDK may reuse an existing
content-addressed upload even when a new filename was requested; clearing old
inputs or bypassing deduplication is neither needed nor a repair.
Repeated stat and byte hashes refuse detected mutation. Streaming uses 1 MiB blocks; bounded safetensors
headers and conditioning JSON are inspected, never materialized as tensors.
FFprobe checks real MP4 width, height, frame count and FPS with a file-only,
MOV/MP4 demuxer policy and external references disabled.

Trust the Comfy host and its root-directory configuration. Like upstream's
path-based validator, verification assumes stable completed artifacts and no
hostile same-user concurrent ancestor-directory rewrites. This is not a sandbox
for a compromised Comfy process. Disk capacity, quotas and job authorization
remain host responsibilities; validation re-reads large files several times.

The fixed output-relative handle satisfies the inspected stock
`H3LoadVideoWithMCtx` resolver and adjacent MCTX/COND naming convention used by
`condload.load_for_clip` / `H3JointConditioning`. A standalone class named
`CONDLoad` was not found in the inspected reference pack; do not assume that
class exists. Native tensor loading, exact runtime revision compatibility,
conditioning values, joint/refine operation, SDK downloads from an actual
executed publisher node and visual continuity are **not** proven by local CPU
tests. Never silently downgrade missing/invalid state to pixel-grade.

The private `_contract` files are generated from the application's four pure
CPU contracts by a whitelisted internal-import-only AST edit. They do not
import the app, add its `src` to sys.path, or alias global module names.
`provenance.json` records exact source/bundle hashes. Rebuild and run the
repository's drift/equality tests after any contract change.
