"""Swap model-role filename aliases, not loader/precision/engine substitutions.

Only compatible files for the declared loader contract may be substituted. Names
are literal ComfyUI inventory entries (including relative subfolders); this module
neither discovers files nor guesses compatibility from a filename. Native H3
continuity profiles and the optional vision-description model are separate roles.
"""
from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from types import MappingProxyType
import model_defaults


def _role(key, label, engine, class_type, input_name, default):
    return MappingProxyType({'key': key, 'label': label, 'engine': engine,
                             'class_type': class_type, 'input': input_name, 'default': default})


_ROLES = (
    _role('flux_unet', 'FLUX Klein diffusion model', 'ltx', 'UNETLoader', 'unet_name', model_defaults.F_UNET_KLEIN),
    _role('flux_clip', 'FLUX Klein text encoder', 'ltx', 'CLIPLoader', 'clip_name', model_defaults.F_CLIP_KLEIN),
    _role('flux_vae', 'FLUX Klein VAE', 'ltx', 'VAELoader', 'vae_name', model_defaults.F_VAE_KLEIN),
    _role('ltx_unet', 'LTX diffusion model', 'ltx', 'UNETLoader', 'unet_name', model_defaults.F_UNET_LTX),
    _role('ltx_clip', 'LTX text encoder', 'ltx', 'CLIPLoader', 'clip_name', model_defaults.F_CLIP_LTX),
    _role('video_vae', 'LTX video VAE', 'ltx', 'VAELoader', 'vae_name', model_defaults.F_VAE_VID),
    _role('audio_vae', 'LTX audio VAE', 'ltx', 'VAELoaderKJ', 'vae_name', model_defaults.F_VAE_AUD),
    _role('ripple_lora', 'Ripple IC-LoRA', 'ltx', 'LoraLoaderModelOnly', 'lora_name', model_defaults.F_LORA_RIPPLE),
    _role('h3_unet', 'H3 diffusion model', 'h3', 'UNETLoader', 'unet_name',
          'minimax_h3_fl2va_pruned_int8_convrot.safetensors'),
    _role('h3_clip', 'H3 text encoder', 'h3', 'CLIPLoader', 'clip_name',
          'qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors'),
    _role('h3_video_vae', 'H3 video VAE', 'h3', 'VAELoader', 'vae_name',
          'minimax_h3_video_vae_fp16.safetensors'),
    _role('h3_audio_vae', 'H3 audio VAE', 'h3', 'VAELoader', 'vae_name',
          'minimax_h3_audio_vae_fp32.safetensors'),
    _role('h3_turbo_lora', 'H3 turbo LoRA', 'h3', 'LoraLoaderModelOnly', 'lora_name',
          'minimax_h3_fl2v_lightx2v_turbo_4step_v0.1_comfy.safetensors'),
    _role('h3_swap_lora', 'H3 character Swap LoRA', 'h3', 'LoraLoaderModelOnly', 'lora_name',
          'H3/h3_character_swap_v1.5.safetensors'),
    _role('h3_upscaler', 'H3 latent upscaler', 'h3', 'MinimaxH3LatentUpscaler3D', 'model_name',
          'minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors'),
)
_DEFAULTS = MappingProxyType({role['key']: role['default'] for role in _ROLES})
LTX_ROLES = tuple(role['key'] for role in _ROLES if role['engine'] == 'ltx')
MAX_FILENAME_LENGTH = 512
_INVALID = 'Invalid model bindings'


def roles() -> list[dict[str, str]]:
    """Return independent public loader contracts; no machine paths or credentials."""
    return [dict(role) for role in _ROLES]


def validate_bindings(value) -> dict[str, str]:
    """Validate overrides without normalizing names or echoing untrusted values."""
    if not isinstance(value, Mapping) or len(value) > len(_DEFAULTS):
        raise ValueError(_INVALID)
    result = {}
    for key, filename in value.items():
        if not isinstance(key, str) or key not in _DEFAULTS:
            raise ValueError(_INVALID)
        if (not isinstance(filename, str) or not filename.strip()
                or len(filename) > MAX_FILENAME_LENGTH
                or filename.startswith(('/', '\\')) or ':' in filename
                or any(unicodedata.category(char).startswith('C') for char in filename)
                or any(part in ('', '.', '..') for part in filename.replace('\\', '/').split('/'))):
            raise ValueError(_INVALID)
        result[key] = filename
    return result


def effective_bindings(overrides=None) -> dict[str, str]:
    """None resolves current settings lazily; explicit {} means declared defaults.

    Freeze the returned names at submission. Workers and replay must pass that
    explicit snapshot, never re-resolve historical recipes against current settings.
    Older compute Target instances without the optional field remain supported.
    """
    if overrides is None:
        import config
        overrides = getattr(config.compute_target(), 'model_bindings', {})
    return dict(_DEFAULTS) | validate_bindings(overrides)
