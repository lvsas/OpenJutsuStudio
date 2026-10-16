"""API-format graph builders for the current FLUX/LTX workflow."""
from config import (F_UNET_KLEIN, F_CLIP_KLEIN, F_VAE_KLEIN, F_UNET_LTX,
                    F_CLIP_LTX, F_VAE_VID, F_VAE_AUD, F_LORA_RIPPLE,
                    RIPPLE_PROMPT, NEG_VIDEO)

def build_frame_edit(image: str | dict, prompt: str, seed: int = 26416064315367,
                     steps: int = 4, cfg: float = 1.0,
                     megapixels: float = 1.0, prefix: str = "og_frame",
                     reference_image: str | dict | None = None) -> dict:
    """FLUX.2 Klein 9B image edit (distilled, 4 steps).

    If reference_image is provided, injects it as a second reference via
    LoadImage + VAEEncode + ReferenceLatent for character/persona consistency.
    """
    graph = {
        "76":  {"class_type": "LoadImage", "inputs": {"image": image}},
        "80":  {"class_type": "ImageScaleToTotalPixels",
                "inputs": {"image": ["76", 0], "upscale_method": "nearest-exact",
                           "megapixels": megapixels, "resolution_steps": 1}},
        "99":  {"class_type": "GetImageSize", "inputs": {"image": ["80", 0]}},
        "70":  {"class_type": "UNETLoader",
                "inputs": {"unet_name": F_UNET_KLEIN, "weight_dtype": "default"}},
        "71":  {"class_type": "CLIPLoader",
                "inputs": {"clip_name": F_CLIP_KLEIN, "type": "flux2", "device": "default"}},
        "72":  {"class_type": "VAELoader", "inputs": {"vae_name": F_VAE_KLEIN}},
        "74":  {"class_type": "CLIPTextEncode",
                "inputs": {"clip": ["71", 0], "text": prompt}},
        "82":  {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["74", 0]}},
        "124": {"class_type": "VAEEncode", "inputs": {"pixels": ["80", 0], "vae": ["72", 0]}},
        "125": {"class_type": "ReferenceLatent",
                "inputs": {"conditioning": ["74", 0], "latent": ["124", 0]}},
        "123": {"class_type": "ReferenceLatent",
                "inputs": {"conditioning": ["82", 0], "latent": ["124", 0]}},
        "66":  {"class_type": "EmptyFlux2LatentImage",
                "inputs": {"width": ["99", 0], "height": ["99", 1], "batch_size": 1}},
        "61":  {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "62":  {"class_type": "Flux2Scheduler",
                "inputs": {"steps": steps, "width": ["99", 0], "height": ["99", 1]}},
        "73":  {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "63":  {"class_type": "CFGGuider",
                "inputs": {"model": ["70", 0], "positive": ["125", 0],
                           "negative": ["123", 0], "cfg": cfg}},
        "64":  {"class_type": "SamplerCustomAdvanced",
                "inputs": {"noise": ["73", 0], "guider": ["63", 0],
                           "sampler": ["61", 0], "sigmas": ["62", 0],
                           "latent_image": ["66", 0]}},
        "65":  {"class_type": "VAEDecode", "inputs": {"samples": ["64", 0], "vae": ["72", 0]}},
        "9":   {"class_type": "SaveImage",
                "inputs": {"images": ["65", 0], "filename_prefix": prefix}},
    }

    # Inject reference image as second LoadImage + VAEEncode + ReferenceLatent
    if reference_image is not None:
        graph["200"] = {"class_type": "LoadImage", "inputs": {"image": reference_image}}
        graph["201"] = {"class_type": "VAEEncode",
                        "inputs": {"pixels": ["200", 0], "vae": ["72", 0]}}
        graph["202"] = {"class_type": "ReferenceLatent",
                        "inputs": {"conditioning": ["125", 0], "latent": ["201", 0]}}
        graph["63"]["inputs"]["positive"] = ["202", 0]

    return graph


def build_ripple(video: str | dict, edited_frame: str | dict, prompt: str = RIPPLE_PROMPT,
                 frames: int = 121, seed: int = 125348341465200, fps: int = 24,
                 width: int = 1280, height: int = 704, steps: int = 16,
                 cfg: float = 1.0, strength: float = 1.2,
                 guide_strength: float = 1.0, prefix: str = "og_ripple") -> dict:
    """LTX 2.5 + Ripple FFAF IC-LoRA.

    `strength` is the key knob:
      1.35 = default; increase if the edit doesn't carry, DECREASE if the
      edit bleeds into content that should stay unchanged.
    """
    return {
        "821": {"class_type": "UNETLoader",
                "inputs": {"unet_name": F_UNET_LTX, "weight_dtype": "default"}},
        "1318": {"class_type": "CLIPLoader",
                 "inputs": {"clip_name": F_CLIP_LTX, "type": "ltxv", "device": "default"}},
        "822": {"class_type": "VAELoader", "inputs": {"vae_name": F_VAE_VID}},
        "448": {"class_type": "VAELoaderKJ",
                "inputs": {"vae_name": F_VAE_AUD, "device": "main_device",
                           "weight_dtype": "bf16"}},
        "1312": {"class_type": "LoraLoaderModelOnly",
                 "inputs": {"model": ["821", 0], "lora_name": F_LORA_RIPPLE,
                            "strength_model": strength}},
        "1320": {"class_type": "PathchSageAttentionKJ",
                 "inputs": {"model": ["1312", 0], "sage_attention": "auto",
                            "allow_compile": False}},
        "1321": {"class_type": "LTX2MemoryEfficientSageAttentionPatch",
                 "inputs": {"model": ["1320", 0], "triton_kernels": True}},
        "790": {"class_type": "VHS_LoadVideo",
                "inputs": {"video": video, "force_rate": float(fps), "custom_width": 0,
                           "custom_height": 0, "frame_load_cap": frames,
                           "skip_first_frames": 0, "select_every_nth": 1, "format": "LTXV"}},
        "782": {"class_type": "ImageResizeKJv2",
                "inputs": {"image": ["790", 0], "width": width, "height": height,
                           "upscale_method": "lanczos", "keep_proportion": "crop",
                           "pad_color": "0, 0, 0", "crop_position": "center",
                           "divisible_by": 2, "device": "cpu"}},
        "1304": {"class_type": "LoadImage", "inputs": {"image": edited_frame}},
        "1294": {"class_type": "ImageResizeKJv2",
                 "inputs": {"image": ["1304", 0], "width": width, "height": height,
                            "upscale_method": "lanczos", "keep_proportion": "crop",
                            "pad_color": "0, 0, 0", "crop_position": "center",
                            "divisible_by": 2, "device": "cpu"}},
        "1288": {"class_type": "BatchImagesNode",
                 "inputs": {"images.image0": ["1294", 0], "images.image1": ["782", 0]}},
        "1289": {"class_type": "Frames Slice",
                 "inputs": {"frames": ["1288", 0], "start": 0, "stop": frames}},
        "567": {"class_type": "EmptyLTXVLatentVideo",
                "inputs": {"width": width, "height": height, "length": frames,
                           "batch_size": 1}},
        "1257": {"class_type": "LTXVEmptyLatentAudio",
                 "inputs": {"frames_number": frames, "frame_rate": float(fps),
                            "batch_size": 1, "audio_vae": ["448", 0]}},
        "814": {"class_type": "CLIPTextEncode",
                "inputs": {"text": prompt, "clip": ["1318", 0]}},
        "388": {"class_type": "CLIPTextEncode",
                "inputs": {"text": NEG_VIDEO, "clip": ["1318", 0]}},
        "563": {"class_type": "LTXVConditioning",
                "inputs": {"positive": ["814", 0], "negative": ["388", 0],
                           "frame_rate": float(fps)}},
        "1330": {"class_type": "LTXAddVideoICLoRAGuide",
                 "inputs": {"positive": ["563", 0], "negative": ["563", 1],
                            "vae": ["822", 0], "latent": ["567", 0],
                            "image": ["1289", 0], "frame_idx": 0,
                            "strength": guide_strength,
                            "latent_downscale_factor": 1.0, "crop": "disabled",
                            "use_tiled_encode": False, "tile_size": 256,
                            "tile_overlap": 64}},
        "1259": {"class_type": "LTXVConcatAVLatent",
                 "inputs": {"video_latent": ["1330", 2], "audio_latent": ["1257", 0]}},
        "1266": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "1265": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "1319": {"class_type": "BasicScheduler",
                 "inputs": {"model": ["1321", 0], "scheduler": "simple",
                            "steps": steps, "denoise": 1.0}},
        "1267": {"class_type": "CFGGuider",
                 "inputs": {"model": ["1321", 0], "positive": ["1330", 0],
                            "negative": ["1330", 1], "cfg": cfg}},
        "1269": {"class_type": "SamplerCustomAdvanced",
                 "inputs": {"noise": ["1266", 0], "guider": ["1267", 0],
                            "sampler": ["1265", 0], "sigmas": ["1319", 0],
                            "latent_image": ["1259", 0]}},
        "423": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["1269", 0]}},
        "571": {"class_type": "LTXVCropGuides",
                "inputs": {"positive": ["1330", 0], "negative": ["1330", 1],
                           "latent": ["423", 0]}},
        "445": {"class_type": "VAEDecode",
                "inputs": {"samples": ["571", 2], "vae": ["822", 0]}},
        "815": {"class_type": "VAEDecodeAudio",
                "inputs": {"samples": ["423", 1], "vae": ["448", 0]}},
        "425": {"class_type": "VHS_VideoCombine",
                "inputs": {"images": ["445", 0], "audio": ["815", 0],
                           "frame_rate": float(fps), "loop_count": 0,
                           "filename_prefix": prefix, "format": "video/h264-mp4",
                           "pingpong": False, "save_output": True}},
    }


