"""Isolated two-pass MiniMax H3 recast graph; no LTX/Ripple orchestration.

Derived from the supplied H3 graph's public node contracts. Model filenames
are explicit target configuration; node/model availability must be checked.
Optional generic references and timestamped guides are separate test arms.
"""
from dataclasses import dataclass

# Product capacity, matching the LTX studio's two visible people. The node's own
# collection is dynamic and larger; that is not a licence to promise more.
REFERENCE_SLOTS = 2
REFERENCE_NODE = 137
GUIDE_NODE = "201"


@dataclass(frozen=True)
class H3Models:
    unet: str = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
    clip: str = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
    video_vae: str = "minimax_h3_video_vae_fp16.safetensors"
    audio_vae: str = "minimax_h3_audio_vae_fp32.safetensors"
    turbo_lora: str = "minimax_h3_fl2v_lightx2v_turbo_4step_v0.1_comfy.safetensors"
    swap_lora: str = "H3/h3_character_swap_v1.5.safetensors"
    upscaler: str = "minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors"


def _integer(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")


def h3_frames(source_frames):
    """Round up to H3's 17k+5 frame grid; source-frame trimming is caller-owned."""
    _integer(source_frames, "source_frames", 1, 3592)
    return 5 + max(0, (source_frames - 5 + 16) // 17) * 17


def _controls(prompt, width, height, output_width, output_height, steps, split_step, seed):
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("A non-empty effective H3 prompt is required")
    for name, value in (("width", width), ("height", height),
                        ("output_width", output_width), ("output_height", output_height)):
        _integer(value, name, 64, 8192)
        if value % 32:
            raise ValueError(f"{name} must be a multiple of 32")
    if output_width < width or output_height < height:
        raise ValueError("H3 upscaler output cannot be smaller than its input")
    _integer(steps, "steps", 2, 100)
    _integer(split_step, "split_step", 1, steps - 1)
    _integer(seed, "seed", 0, 2**64 - 1)


def _guide(g, image, frame, source_frames, slot):
    if frame is not None:
        _integer(frame, "guide_frame", 0, source_frames - 1)
        if image is None:
            raise ValueError("guide_frame requires guide_image")
    if image is None:
        return
    g[GUIDE_NODE] = {"class_type": "LoadImage", "inputs": {"image": image}}
    g["136"]["inputs"][f"ref_images.ref_image_{slot}"] = [GUIDE_NODE, 0]
    if frame is None:
        return  # Extra Picture reference only: no temporal constraint.
    for node_id, guider, latent in (("202", "126", ["136", 1]),
                                    ("203", "176", ["171", 0])):
        g[node_id] = {"class_type": "MiniMaxH3AddGuide", "inputs": {
            "positive": ["136", 0], "latent": latent, "frame_idx": frame,
            "vae": ["119", 0], "image": [GUIDE_NODE, 0]}}
        g[guider]["inputs"]["conditioning"] = [node_id, 0]


def _references(reference):
    """Normalize one reference or an ordered sequence of them.

    Capacity is a product decision that matches LTX (two visible people). The node
    accepts a dynamic collection of up to nine slots, but that says nothing about
    reliable per-person assignment, so the graph refuses to imply more than two.
    """
    if isinstance(reference, (str, dict)):
        items = [reference]
    elif isinstance(reference, (list, tuple)):
        items = list(reference)
    else:
        raise ValueError("H3 references must be a filename, an asset or a sequence of them")
    if not 1 <= len(items) <= REFERENCE_SLOTS:
        raise ValueError(f"H3 accepts between 1 and {REFERENCE_SLOTS} character references")
    if any(isinstance(item, (list, tuple)) for item in items):
        raise ValueError("Each H3 character reference must be a single asset")
    return items


def build_h3_recast(video, reference, prompt, *, source_frames, width=512, height=288,
                    output_width=1024, output_height=576, seed=302929098223082,
                    steps=6, split_step=3, models=None, guide_image=None, guide_frame=None,
                    reference_size="match", filename_prefix="OpenGenjutsu/h3-recast", source_audio=True):
    """Build an API-format H3 graph, preserving the effective prompt verbatim.

    Fixed 24fps H3 input. Character references occupy ref_image slots in the order
    given; a guide takes the next free slot, so adding a second character never
    displaces temporal conditioning. Source audio is muxed rather than regenerated.
    The caller pads source clips to the H3 frame grid and trims downloaded output.
    This builder alone is not a validated Studio job adapter or replay contract.
    """
    _controls(prompt, width, height, output_width, output_height, steps, split_step, seed)
    references = _references(reference)
    length = h3_frames(source_frames)
    if reference_size not in {"match", "max"}:
        raise ValueError("reference_size must be match or max")
    m = models or H3Models()
    g = {}

    def node(key, kind, **inputs):
        g[key] = {"class_type": kind, "inputs": inputs}

    node("127", "UNETLoader", unet_name=m.unet, weight_dtype="default")
    node("157", "LoraLoaderModelOnly", model=["127", 0], lora_name=m.turbo_lora, strength_model=0.9)
    node("159", "LoraLoaderModelOnly", model=["157", 0], lora_name=m.swap_lora, strength_model=1.0)
    node("160", "ModelAttentionBackend", model=["159", 0], attention="comfy kitchen attention")
    node("128", "CLIPLoader", clip_name=m.clip, type="minimax", device="default")
    node("119", "VAELoader", vae_name=m.video_vae)
    node("120", "VAELoader", vae_name=m.audio_vae)
    for index, image in enumerate(references):
        node(str(REFERENCE_NODE + index), "LoadImage", image=image)
    node("155", "VHS_LoadVideo", video=video, force_rate=24, custom_width=0,
         custom_height=0, frame_load_cap=source_frames, skip_first_frames=0,
         select_every_nth=1, format="AnimateDiff")
    node("161", "ResizeImageMaskNode", input=["155", 0], resize_type="scale dimensions",
         scale_method="area", **{"resize_type.width": width, "resize_type.height": height,
                                  "resize_type.crop": "center"})
    slots = {f"ref_images.ref_image_{index}": [str(REFERENCE_NODE + index), 0]
             for index in range(len(references))}
    node("136", "MiniMaxH3ReferenceToVideo", prompt=prompt, width=width, height=height,
         length=length, ref_image_size=reference_size, clip=["128", 0], vae=["119", 0],
         audio_vae=["120", 0], **slots, **{"ref_videos.ref_video_0": ["161", 0],
                                           "ref_video_audios.ref_video_audio_0": ["155", 2]})
    node("129", "RandomNoise", noise_seed=seed)
    node("123", "KSamplerSelect", sampler_name="er_sde")
    for sched, split, model in (("124", "172", "159"), ("173", "174", "160")):
        node(sched, "BasicScheduler", scheduler="beta57", steps=steps, denoise=1.0, model=[model, 0])
        node(split, "SplitSigmas", step=split_step, sigmas=[sched, 0])
    node("126", "BasicGuider", model=["159", 0], conditioning=["136", 0])
    node("125", "SamplerCustomAdvanced", noise=["129", 0], guider=["126", 0],
         sampler=["123", 0], sigmas=["172", 0], latent_image=["136", 1])
    node("167", "LTXVSeparateAVLatent", av_latent=["125", 1])
    node("169", "MinimaxH3LatentUpscaler3D", latent=["167", 0], model_name=m.upscaler,
         mode="target dimensions", **{"mode.width": output_width, "mode.height": output_height},
         align=32, enable_temporal_chunking=True, force_unload=False, device="cuda", precision="fp16")
    node("171", "LTXVConcatAVLatent", video_latent=["169", 0], audio_latent=["167", 1])
    node("176", "BasicGuider", model=["160", 0], conditioning=["136", 0])
    node("170", "SamplerCustomAdvanced", noise=["129", 0], guider=["176", 0],
         sampler=["123", 0], sigmas=["174", 1], latent_image=["171", 0])
    node("122", "VAEDecode", samples=["170", 1], vae=["119", 0])
    node("156", "VHS_VideoCombine", frame_rate=24, loop_count=0, filename_prefix=filename_prefix,
         format="video/h264-mp4", pix_fmt="yuv420p", crf=19, save_metadata=True,
         trim_to_audio=False, pingpong=False, save_output=True, images=["122", 0], audio=["155", 2])
    if type(source_audio) is not bool:
        raise ValueError("source_audio must be boolean")
    if not source_audio:
        g["136"]["inputs"].pop("ref_video_audios.ref_video_audio_0")
        g["156"]["inputs"].pop("audio")
    _guide(g, guide_image, guide_frame, source_frames, len(references))
    return g
