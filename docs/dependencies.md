# Dependencies

What this repository needs to run, verified against a live instance rather than assembled from
memory. Read this before writing an install guide or opening the repository to anyone else.

## How this was verified

| | |
|---|---|
| Method | `GET /object_info` on the reference instance, then a mechanical diff against every `class_type` and every `*_name` value found in `workflows/` and `src/h3_graphs.py` |
| Instance | ComfyUI **0.40.0**, Python 3.12.1, Linux, RTX 3090 (25.3 GB), launched with `--use-pytorch-cross-attention --cache-lru 40 --fp16-intermediates --listen <lan-ip>` |
| Inventory size | 6 007 node classes, 57 custom packs installed |
| Fingerprint | `object_info.json` sha256 begins `5138fa807c8cd46e2e9c88f3a88594f8` (full file under `work/dep-audit/`) |

The instance is a **workstation**, not a minimal install: it carries 57 packs for unrelated
work. What matters for this repository is far smaller, and is enumerated below.

## The list, by category

Machine-readable in **`dependencies.json`** at the repository root; verify a machine with:

```bash
python3 scripts/check_dependencies.py --host http://127.0.0.1:8188
python3 scripts/check_dependencies.py --host <url> --include-planned   # also the character generator
```

It reports what is missing per category, names the pack that owns a missing node, distinguishes an
out-of-date ComfyUI from an incomplete one, and exits non-zero so it can gate a deployment.

### Custom nodes — 5 packs

| Pack | Nodes we need | Needed by |
|---|---|---|
| **ComfyUI-VideoHelperSuite** | `VHS_LoadVideo`, `VHS_VideoCombine` | all three workflows |
| **ComfyUI-LTXVideo** | `LTXAddVideoICLoRAGuide` | LTX / Ripple |
| **ComfyUI-KJNodes** | `ImageResizeKJv2`, `PathchSageAttentionKJ`, `VAELoaderKJ`, `LTX2MemoryEfficientSageAttentionPatch` | LTX / Ripple |
| **ComfyUI_Res4lyf** | `Frames Slice` | LTX / Ripple |
| **MiniMaxH3-LatentUpscaler** | `MinimaxH3LatentUpscaler3D` | H3 |

Plus **34 nodes from ComfyUI core** itself — 23 from `comfy_extras` and 11 from the base — listed in
`dependencies.json` so a version floor can be checked rather than guessed.

### Models — 12 files, in ComfyUI's own folders

| Folder | File | Role |
|---|---|---|
| `diffusion_models` | `minimax_h3_fl2va_pruned_int8_convrot.safetensors` | H3 base |
| `vae` | `minimax_h3_video_vae_fp16.safetensors` | H3 video decode |
| `vae` | `minimax_h3_audio_vae_fp32.safetensors` | H3 audio decode |
| `text_encoders` | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | H3 text encoder |
| `upscale_models` | `minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors` | H3 latent upscaler |
| `diffusion_models` | `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` | LTX transformer |
| `vae` | `ltx-2.5-video-vae-conv-bf16.safetensors` | LTX video decode |
| `vae` | `ltx-2.5-audio-vae-bf16.safetensors` | LTX audio decode |
| `text_encoders` | `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` | LTX text encoder |
| `diffusion_models` | `flux-2-klein-9b-fp8.safetensors` | first-frame editor |
| `vae` | `full_encoder_small_decoder.safetensors` | first-frame editor VAE |
| `text_encoders` | `qwen_3_8b_fp8mixed.safetensors` | first-frame editor text encoder |

### LoRAs — 3 files

| File | Role | Author |
|---|---|---|
| `H3/h3_character_swap_v1.5.safetensors` | the character-swap adapter the H3 studio is built on | akatz-ai |
| `minimax_h3_fl2v_lightx2v_turbo_4step_v0.1_comfy.safetensors` | step distillation, H3 speed | — |
| `LTX25_Ripple_v11.safetensors` | carries an approved edit through motion | WepeNerd |

The H3 LoRA keeps its `H3/` subfolder, because the workflow names it that way.

## 1. Python

`requirements.txt` is the whole list; the application has no other Python dependency.

```
fastapi>=0.115,<1.0
uvicorn[standard]>=0.30,<1.0
python-multipart>=0.0.9
comfy-sdk>=0.5,<0.6
```

Python **3.12** is enforced by `scripts/run_app.sh`, which refuses to start on another version.

## 2. System

| Dependency | Used for | Presence on the reference machine |
|---|---|---|
| `ffmpeg` | every render, the comparison reel, audio restoration | 5.1.9 (Debian 12) |
| `ffprobe` | duration, fps and frame counting before a render | included with ffmpeg |
| `node` | `tests/h3_studio_contract.mjs`, the front-end contract test only | present |
| DejaVu Sans + Liberation Sans Narrow | reel typography and glyph coverage | 8 faces installed |

Neither font is vendored in the repository; the reel resolves them by path and falls back to
`Sans` if absent. Liberation Sans Narrow is the metric-compatible stand-in for the `Arial Narrow`
the stylesheet asks for, and it lives in the `fonts-liberation` package on Debian.

## 3. ComfyUI core

The reference instance runs ComfyUI **0.40.0**. Ten of our node classes come straight from the
core, so nothing needs installing for them — but it does mean the version floor matters, because
MiniMax H3 support only landed in core recently:

| Core module | Node classes we use |
|---|---|
| `nodes_minimax_h3` | `MiniMaxH3ReferenceToVideo`, `MiniMaxH3AddGuide` |
| `nodes_custom_sampler` | `SamplerCustomAdvanced`, `BasicGuider`, `CFGGuider`, `BasicScheduler`, `KSamplerSelect`, `RandomNoise`, `SplitSigmas` |
| `nodes_lt`, `nodes_lt_audio` | `EmptyLTXVLatentVideo`, `LTXVConditioning`, `LTXVCropGuides`, `LTXVConcatAVLatent`, `LTXVSeparateAVLatent`, `LTXVEmptyLatentAudio` |
| `nodes_flux`, `nodes_edit_model` | `EmptyFlux2LatentImage`, `Flux2Scheduler`, `ReferenceLatent` |
| `nodes_audio` | `VAEDecodeAudio` |
| `nodes_post_processing` | `BatchImagesNode`, `ResizeImageMaskNode` |
| `nodes_images`, `nodes_model_advanced` | `GetImageSize`, `ModelAttentionBackend` |
| `nodes` | `LoadImage`, `UNETLoader`, `VAELoader`, `CLIPLoader`, `CLIPTextEncode`, `LoraLoaderModelOnly`, `VAEDecode`, `VAEEncode`, `ConditioningZeroOut`, `ImageScaleToTotalPixels`, `SaveImage` |

**Finding.** MiniMax H3 is core. An earlier assumption that H3 needed a companion pack is wrong
as of this version, and no H3 node has to be installed.

## 4. Custom node packs

Five packs, and only five, are required by the workflows. All 43 `class_type` values used by the
repository resolve on the reference instance — **zero missing**.

| Upstream pack | Node classes we need | Status |
|---|---|---|
| **ComfyUI-VideoHelperSuite** | `VHS_LoadVideo`, `VHS_VideoCombine` | own pack, installed |
| **ComfyUI-LTXVideo** | `LTXAddVideoICLoRAGuide` | own pack, installed |
| **ComfyUI-KJNodes** | `ImageResizeKJv2`, `PathchSageAttentionKJ`, `VAELoaderKJ`, `LTX2MemoryEfficientSageAttentionPatch` | bundled — see below |
| **ComfyUI_Res4lyf** | `Frames Slice` | bundled — see below |
| **ComfyUI-MiniMaxH3-LatentUpscaler** | `MinimaxH3LatentUpscaler3D` | installed, **name collision — see below** |

### Finding: the workflow-encrypt bundle

On the reference instance, `ImageResizeKJv2`, `PathchSageAttentionKJ`, `VAELoaderKJ`,
`LTX2MemoryEfficientSageAttentionPatch` and `Frames Slice` are reported by `/object_info` as
belonging to a pack named **`custom_nodes.comfyui-workflow-encrypt`**, which carries **3 543 node
classes** — KJNodes, Res4lyf and a great deal else vendored into one folder.

Consequences that matter:

1. **That is a local artefact, not a dependency name.** Nobody can install
   "comfyui-workflow-encrypt" from the registry and get `ImageResizeKJv2`. An install guide must
   name the upstream packs — KJNodes and Res4lyf — and let the node names resolve from there.
2. **A pack name is not a pack identity.** Verify dependencies by *node class* against
   `/object_info`, never by folder name. `scripts/probe_wireability.py` and
   `scripts/validate_workflow.py` in the `comfyui-workflow-audit` skill both do it this way.

### Finding: two packs claim the H3 latent upscaler

The instance carries both `ComfyUI-MiniMaxH3_LatentUpscaler` (9 nodes) and
`Comfyui_Minimax_h3_latent_Upscaler` (5 nodes). Our node resolves to the second one. Which pack
owns a class is decided by load order, so this is fragile: the install guide must pin one, and a
startup check should assert the resolved `python_module`.

## 5. Models

Filenames exactly as the workflows reference them, all confirmed present in the loaders' COMBO
options on the reference instance.

### LTX / Ripple path

| Field | File |
|---|---|
| `unet_name` | `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` |
| `vae_name` | `ltx-2.5-video-vae-conv-bf16.safetensors` |
| `vae_name` | `ltx-2.5-audio-vae-bf16.safetensors` |
| `clip_name` | `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` |
| `lora_name` | `LTX25_Ripple_v11.safetensors` |

### FLUX path (first animation step of the LTX frame edit)

| Field | File |
|---|---|
| `unet_name` | `flux-2-klein-9b-fp8.safetensors` |
| `vae_name` | `full_encoder_small_decoder.safetensors` |
| `clip_name` | `qwen_3_8b_fp8mixed.safetensors` |

### MiniMax H3 path

| Role | File |
|---|---|
| `unet_name` | `minimax_h3_fl2va_pruned_int8_convrot.safetensors` |
| `clip_name` | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` |
| video VAE | `minimax_h3_video_vae_fp16.safetensors` |
| audio VAE | `minimax_h3_audio_vae_fp32.safetensors` |
| character-swap LoRA | `H3/h3_character_swap_v1.5.safetensors` |
| speed LoRA | `minimax_h3_fl2v_lightx2v_turbo_4step_v0.1_comfy.safetensors` |
| latent upscaler | `minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors` |

### Deliberately not required

The instance holds 217 LoRAs, including a large NSFW library, and 33 UNets for unrelated
projects. **None of them is referenced by this repository.** An install guide must list the files
above and nothing else, so a third party downloads a known set instead of mirroring a
workstation.

## 6. Runtime configuration

| Variable | Default | Note |
|---|---|---|
| `OPENGENJUTSU_PORT` | `8000` | |
| `OPENGENJUTSU_HOST` | `127.0.0.1` | loopback by default; a single explicit address is allowed for a trusted LAN or a tunnel, wildcard binds are refused |
| `OPENGENJUTSU_COMFY_BASE_URL` | `http://127.0.0.1:8189` | the SDK's `COMFY_BASE_URL` is exported from this |
| `OPENGENJUTSU_H3_STUDIO_ENABLED` | enabled | set to `0` to hide the H3 studio |

**Finding: the default Comfy target is a local proxy that this machine does not run.** Nothing
listens on `127.0.0.1:8189` here; the reachable ComfyUI is a separate machine on the local network,
on port 8188. An address is deliberately not written down here — the repository carries none.
Starting the app with the defaults therefore gives a studio whose readiness check fails. Two
things follow for a third party:

- the install guide must state that a Comfy target has to be provided, either as a local proxy or
  through `OPENGENJUTSU_COMFY_BASE_URL`;
- `docs/local-setup.md` should describe that proxy, because as written the default points at
  something the reader has no reason to know about.

The app is reached over loopback and is expected to stay bound there: the maintainer's access is
an SSH local forward (`ssh -L 8000:127.0.0.1:8000 <host>`), which fails if the bind moves to a
LAN address. The application has no authentication, which is the other reason loopback is the
right default.

## 7. Licence status

Model **files are not redistributed** by this repository — only their names appear, inside the
workflow JSON. A user must obtain them separately, which puts the licence question on the user, but
this project still has to answer it for two reasons: the competition requires lawful submissions, and
the stated goal is selling work produced with these models.

**The full position is in [`validation/model-licences.md`](validation/model-licences.md)**, verified
against the publishers' own pages. Read it before invoicing anything. In one line: the LTX 2.5 +
Ripple path is licensed for commercial work below the revenue threshold, the FLUX.2 Klein first-frame
step is under a non-commercial licence, and the MiniMax H3 licence excludes the European Union.

`docs/validation/h3-license-gate.md` holds the H3 analysis, including the organizer guidance that
permits contest validation — which is a different question from commercial use.

## 8. What a third party installs

1. Python 3.12, `pip install -r requirements.txt`.
2. `ffmpeg` and `ffprobe` on `PATH`.
3. ComfyUI, current enough to contain `nodes_minimax_h3`.
4. Five custom packs by upstream name: VideoHelperSuite, LTXVideo, KJNodes, Res4lyf,
   MiniMaxH3-LatentUpscaler.
5. The model files in section 5, placed in ComfyUI's `models/unet`, `models/vae`, `models/clip`,
   `models/loras` (the H3 LoRA keeps its `H3/` subfolder, because the workflow names it that way).
6. A Comfy target the app can reach, and a GPU with enough VRAM for the model in use.
7. `bash scripts/run_app.sh`, then open the port it prints.
