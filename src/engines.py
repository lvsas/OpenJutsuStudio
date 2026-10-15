"""Model-specific frame edit and propagation engines."""
from abc import ABC, abstractmethod
from config import (F_UNET_KLEIN, F_CLIP_KLEIN, F_VAE_KLEIN, F_UNET_LTX,
                    F_CLIP_LTX, F_VAE_VID, F_VAE_AUD, F_LORA_RIPPLE)
from graphs import build_frame_edit, build_ripple
from comfy_transport import _run_graph

class Engine(ABC):
    """A video-editing engine. Implementations swap the model stack while the
    pipeline (edit frame 0 -> propagate) stays the same."""
    name: str = "abstract"
    label: str = "Abstract"
    requires: list[str] = []

    @abstractmethod
    def edit_frame(self, client, image: str, prompt: str, **kw) -> str:
        """Edit a still frame. Returns the stored filename."""

    @abstractmethod
    def propagate(self, client, video: str, edited_frame: str, prompt: str, **kw) -> str:
        """Propagate the frame edit across the video. Returns the output filename."""


class LTXRippleEngine(Engine):
    name = "ltx25-ripple"
    label = "LTX 2.5 + Ripple IC-LoRA"
    requires = [F_UNET_LTX, F_CLIP_LTX, F_VAE_VID, F_VAE_AUD, F_LORA_RIPPLE,
                F_UNET_KLEIN, F_CLIP_KLEIN, F_VAE_KLEIN]

    def edit_frame(self, client, image, prompt, steps=4, seed=26416064315367, **kw):
        # image may be a filename string or an Asset reference dict
        if isinstance(image, dict):
            img_ref = image
        else:
            img_ref = {"__type": "core/ASSET", "info": {"file_path": image}}
        g = build_frame_edit(img_ref, prompt, seed=seed, steps=steps)
        return _run_graph(client, g, "9")

    def propagate(self, client, video, edited_frame, prompt, frames=121, seed=125348341465200,
                  width=768, height=416, steps=8, strength=1.2, **kw):
        # both video (VHS_LoadVideo) and edited_frame (LoadImage) need core/ASSET refs
        if isinstance(video, dict):
            vid_ref = video
        else:
            vid_ref = {"__type": "core/ASSET", "info": {"file_path": video}}
        if isinstance(edited_frame, dict):
            frame_ref = edited_frame
        else:
            frame_ref = {"__type": "core/ASSET", "info": {"file_path": edited_frame}}
        g = build_ripple(vid_ref, frame_ref, prompt=prompt, frames=frames, seed=seed,
                         width=width, height=height, steps=steps, strength=strength)
        return _run_graph(client, g, "425")


class MiniMaxH3Engine(Engine):
    """Alternative engine — reuses the same pipeline shape with the H3 model
    stack (ref2va / fl2va + motion adapters)."""
    name = "minimax-h3"
    label = "MiniMax H3"
    requires = []

    def edit_frame(self, client, image, prompt, **kw):
        raise NotImplementedError(
            "MiniMax H3 engine: frame editing reuses FLUX.2 Klein "
            "(engine-agnostic step). Call LTXRippleEngine.edit_frame.")

    def propagate(self, client, video, edited_frame, prompt, **kw):
        raise NotImplementedError(
            "MiniMax H3 propagation is not wired yet. The H3 motion-transfer "
            "path (ref2va + motion adapter) is the next engine to implement.")


ENGINES = {e.name: e for e in (LTXRippleEngine(), MiniMaxH3Engine())}
