# Dependencies

Prepare only the engine you intend to use. [Install the app/proxy](local-setup.md)
separately from [ComfyUI and its custom nodes](executor-setup.md).

`dependencies.json` declares node classes, file roles, public sources and pins.
The scoped checker reads the actual Swap graph builders:

```bash
python3 scripts/check_dependencies.py --host http://127.0.0.1:8188 --engine h3
python3 scripts/check_dependencies.py --host http://127.0.0.1:8188 --engine ltx
```

The downloader covers **7 H3 Swap files**, **8 LTX Swap files**, or **4 Character
files**, not all features. The Character files live in a gated Hugging Face
repository: they are pinned to a revision and sized, but they publish no hash and
they need `HF_TOKEN` (after accepting the model terms) to download. `make deps`
reports them as gated instead of failing an unauthenticated request.
It does not install custom nodes. Descriptions, Characters and native continuation
have additional prerequisites. Inventory verifies loader choices, not CUDA
compatibility, installed source bytes or rendering quality.

### Custom nodes — original Swap baseline

| Pack | Nodes we need | Needed by |
|---|---|---|
| **ComfyUI-VideoHelperSuite** | `VHS_LoadVideo`, `VHS_VideoCombine` | all three workflows |
| **ComfyUI-LTXVideo** | `LTXAddVideoICLoRAGuide` | LTX / Ripple |
| **ComfyUI-KJNodes** | `ImageResizeKJv2`, `PathchSageAttentionKJ`, `VAELoaderKJ`, `LTX2MemoryEfficientSageAttentionPatch` | LTX / Ripple |
| **ComfyUI_Res4lyf** | `Frames Slice` | LTX / Ripple |
| **MiniMaxH3-LatentUpscaler** | `MinimaxH3LatentUpscaler3D` | H3 |

ComfyUI core classes are also listed in `dependencies.json` so availability can be checked rather
than guessed. The experimental native compiler adds the requirements below.

### Native H3 continuation — additional prerequisites

Native capture/continuation use OBVPM mechanisms and the project-owned
[continuity pack](../custom_nodes/opengenjutsu_continuity/README.md). These are not
required for a video-only Swap. The upstream saver writes MP4/MCTX/COND; our
publisher exposes them as SDK outputs and the restager makes an imported family
available to its loader. Transport does not replace native temporal operations.

| Pack | Role |
|---|---|
| [comfyui-obvpm](https://github.com/chanon/comfyui-obvpm) | Native routing and bundle contracts. |
| [comfyui-obvpm-timeline](https://github.com/chanon/comfyui-obvpm-timeline) | MCTX/COND loaders, pinning and saver. |
| [ComfyUI-OpenJutsu-Capsules](https://github.com/lvsas/ComfyUI-OpenJutsu-Capsules) | `OpenGenjutsuH3PublishClip`, `OpenGenjutsuH3RestageFamily` and family publication. |

The declared capsule-pack source pin is
`7288a04bbdde5cd793d0ec38c4de3c49a33840d0`. This is provenance, not a claim that
inventory verifies running source bytes. See the manifest for each source pin.
Native model filenames are frozen; a measured weight hash is optional enrichment,
not an invented caller-supplied requirement. Runtime bindings are distinct from
installable default files.

Native graph contracts (additional classes, not base Swap installation):

| Provider | Classes |
|---|---|
| OBVPM | `AudioOptionalGate (obvpm)`, `Bundle (obvpm)`, `LazyCaseSwitch (obvpm)`, `LazySwitch (obvpm)`, `ModelOptionalGate (obvpm)`, `MuteGate (obvpm)`, `Unbundle (obvpm)`, `ValuePresets (obvpm)` |
| OBVPM Timeline | `H3LoadVideoWithMCtx`, `H3LoadMCtx`, `H3MCtxApplyPins`, `H3MCtxPinSpec`, `H3TrimAndSaveVideoWithMCtx`, `H3VramHeadroom` |
| Helpers/core | `INTConstant`, `MiniMaxH3SigmaShift`, `PrimitiveBoolean`, `SaveText` |

Template binding tokens `__H3_BIND_UNET__`, `__H3_BIND_CLIP__`,
`__H3_BIND_VIDEO_VAE__` and `__H3_BIND_AUDIO_VAE__` are resolved model roles,
not downloadable filenames.

### Models — 12 files, in ComfyUI's own folders

| Folder | File | Role |
|---|---|---|
| `diffusion_models` | `minimax_h3_fl2va_pruned_int8_convrot.safetensors` | H3 base |
| `vae` | `minimax_h3_video_vae_fp16.safetensors` | H3 video decode |
| `vae` | `minimax_h3_audio_vae_fp32.safetensors` | H3 audio decode |
| `text_encoders` | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | H3 text encoder |
| `latent_upscale_models` | `minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors` | H3 latent upscaler |
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

FFmpeg and ffprobe are required on the app host and executor. Node.js runs frontend
contract tests, not inference. Reel typography uses installed DejaVu Sans and
Liberation Sans Narrow with a Sans fallback; no proprietary font is bundled.
See [setup](local-setup.md) for system packages.

## 3. ComfyUI core

The reference instance runs ComfyUI **0.40.0**. Ten of our node classes come straight from the
core, so nothing needs installing for them — but it does mean the version floor matters, because
MiniMax H3 support only landed in core recently:

| Core module | Node classes we use |
|---|---|
| `nodes_minimax_h3` | `MiniMaxH3ReferenceToVideo`, `MiniMaxH3AddGuide` |
| `nodes_custom_sampler` | `SamplerCustomAdvanced`, `BasicGuider`, `CFGGuider`, `BasicScheduler`, `KSamplerSelect`, `RandomNoise`, `SplitSigmas` |
| `nodes_lt`, `nodes_lt_audio` | `EmptyLTXVLatentVideo`, `LTXVConditioning`, `LTXVCropGuides`, `LTXVConcatAVLatent`, `LTXVSeparateAVLatent`, `LTXVEmptyLatentAudio` |
| `nodes_flux`, `nodes_edit_model` | `EmptyFlux2LatentImage`, `Flux2Scheduler`, `ReferenceLatent`, `Flux3LayoutPrompt` |
| `nodes_audio` | `VAEDecodeAudio` |
| `nodes_post_processing` | `BatchImagesNode`, `ResizeImageMaskNode` |
| `nodes_images`, `nodes_model_advanced` | `GetImageSize`, `ModelAttentionBackend` |
| `nodes` | `LoadImage`, `UNETLoader`, `VAELoader`, `CLIPLoader`, `CLIPTextEncode`, `LoraLoaderModelOnly`, `KSampler`, `VAEDecode`, `VAEEncode`, `ConditioningZeroOut`, `ImageScaleToTotalPixels`, `SaveImage` |
| `nodes_textgen` | `TextGenerate` — this is what runs the character generator's prompt upsampler |
| `nodes_resolution` | `ResolutionSelector` |
| `nodes_bounding_boxes` | `CreateBoundingBoxes` |
| `nodes_logic` | `ComfySwitchNode` |
| `nodes_preview_any`, `nodes_primitive` | `PreviewAny`, `PrimitiveStringMultiline` |

**Finding.** MiniMax H3 model/reference/sampling support is core. Its native MCTX loaders, pins and
savers are separate OBVPM extension contracts; core model support alone does not provide them.

## 4. Custom node packs

Install standalone upstream packs, not a workstation's bundled plugins. The
[executor guide](executor-setup.md#2-install-only-the-needed-custom-node-packs)
provides source revisions and procedure. Avoid duplicate owners of a node class.
Checks use the actual class and loader choices, not a local folder name. Preserve
existing installations instead of resetting or overwriting them.

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

### Character generator path (FLUX 3 Image Klein)

The upstream workflow for this path is kept in the repository at
`workflows/flux3-klein-official-t2i.json`, so the contract covers the vendor's own graph as well as
ours. Every file below is confirmed present on the reference instance.

| Role | File |
|---|---|
| `unet_name` | `flux3-image-klein-base-int8-convrot.safetensors` (in the `flux/` subfolder here) |
| `clip_name` | `qwen3vl_4b_int8_convrot.safetensors`, `CLIPLoader` type `flux3` — this is what feeds the sampler |
| `clip_name` | `qwen3.5_9b_flux3_prompt_upsampler_int8_convrot.safetensors` — writes the caption, via `TextGenerate` |
| `vae_name` | `flux2-vae.safetensors` |

Two notes that cost time to establish. The prompt upsampler is **not** the conditioning encoder:
wiring it to the sampler fails with `mat1 and mat2 shapes cannot be multiplied`. And the upstream
workflow names the diffusion model **without** a folder prefix, which an install that keeps the file
in a subfolder must add, or the audit refuses the name with `value_not_in_list`.

### Deliberately not required

The reference executor also holds assets for unrelated projects. **They are not
application dependencies.** Use the declared roles and sources in `dependencies.json`
rather than mirroring a workstation. The current fixed Swap-file installer and
[executor setup guide](executor-setup.md) define the portable setup scope.

## 6. Runtime configuration

The app defaults to `127.0.0.1:8000` and the local API-v2 proxy on
`http://127.0.0.1:8189`. Start the proxy explicitly, then use **Settings → Test /
Save** for the target and compatible model-file aliases. Keys remain write-only;
never put them in a report or Git. See [setup](local-setup.md) for overrides.

## 7. Licences and coverage

Apache-2.0 application code does not relicense models or third-party packs. See the
[component licence/source map](model-licences.md) for the exact files you obtain.

Characters additionally needs FLUX 3, its conditioning encoder, prompt upsampler
and `flux2-vae.safetensors`; this is not the first-frame editor VAE. Native H3 has
its own reference-to-video model and prompt-refiner encoder. These paths are
**not fully provisioned by the Swap downloader**. `--engine all` means both Swaps,
not every application feature.

## Named by the adopted continuity and prompt workflows

These are referenced by `workflows/h3-continuity-latent.api.json` and
`workflows/h3-prompt-r2va.template.json`. They are recorded so the inventory check
stays honest; the pack origin of the node groups above is not yet verified on the
target machine. A style adapter listed as optional is not required to generate.

### Nodes

- `BlockSparseAttention`
- `CleanVRAM (obvpm)`
- `ComfyMathExpression`
- `ComfyNotNode`
- `CustomCombo`
- `H3ContextWindows`
- `H3JointAudioMask`
- `H3JointConditioning`
- `H3JointLatent`
- `H3JointRender`
- `ImageBatchMulti`
- `JoinStringMulti`
- `LoadAudio`
- `MiniMaxH3MemoryEfficientSageAttentionPatch`
- `MiniMaxH3TurboLoRA`
- `PixaromaH3AudioSync`
- `PrimitiveFloat`
- `SeedNode`
- `SpectrumApplyMiniMaxH3`
- `StringConstantMultiline`
- `easy anythingIndexSwitch`

### Models and adapters

No style LoRA: the adopted continuity template is compiled with its four
dormant style adapters removed.

- `QWEN/qwen3vl_4b_fp8_scaled.safetensors`
- `minimax_h3_ref2va_pruned_int8_convrot.safetensors`
