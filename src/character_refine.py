"""Versioned optional FaceDetailer extension; preserve the vendor base and legacy evidence."""
from __future__ import annotations

import copy

FACE_REFINE_POLICY = 2
REFINED_OUTPUT_NODE = "character_refined"
REFINE_MODEL_ROLES = {"face_detector": "bbox/face_yolov8m.pt", "face_sam": "sam_vit_b_01ec64.pth"}


def face_prompt_v2(facts, selections):
    """Stable face-only contract: no extraction from arbitrary full-scene prose."""
    explicit = {key: value for key, value in selections.items() if value != "model_decides"}
    face = explicit.get("face") or (facts or {}).get("face")
    parts = ["Refine only the existing face."]
    if face:
        parts.append("Facial characteristics: " + face.rstrip(".!? ") + ".")
    if explicit.get("skin_tone"):
        parts.append("Skin tone: " + explicit["skin_tone"].rstrip(".!? ") + ".")
    parts.append("Preserve the input face's identity, proportions, apparent age, expression and gaze. "
                 "Follow the input image for unspecified facial details; improve local detail without redesigning the face.")
    return " ".join(parts)


def append_face_refine(graph, *, seed: int, job_id: str, face_prompt: str | None = None):
    """Append the installed Impact-Pack schema using the donor's actual conditioning."""
    graph = copy.deepcopy(graph)
    positive = ["18:4", 0]  # Frozen policy1 evidence only; new requests always supply policy2 text.
    if face_prompt is not None:
        if not isinstance(face_prompt, str) or not face_prompt.strip():
            raise ValueError("Face refinement requires non-empty facial conditioning")
        graph["character_face_positive"] = {"class_type": "CLIPTextEncode", "inputs": {
            "clip": ["18:2", 0], "text": face_prompt}}
        positive = ["character_face_positive", 0]
    graph["character_bbox"] = {"class_type": "UltralyticsDetectorProvider", "inputs": {
        "model_name": REFINE_MODEL_ROLES["face_detector"]}}
    graph["character_sam"] = {"class_type": "SAMLoader", "inputs": {
        "model_name": REFINE_MODEL_ROLES["face_sam"], "device_mode": "AUTO"}}
    graph["character_detail"] = {"class_type": "FaceDetailer", "inputs": {
        "image": ["18:8", 0], "model": ["18:1", 0], "clip": ["18:2", 0],
        "vae": ["18:3", 0], "positive": positive, "negative": ["18:5", 0],
        "bbox_detector": ["character_bbox", 0], "sam_model_opt": ["character_sam", 0],
        "guide_size": 768, "guide_size_for": True, "max_size": 1024, "seed": seed,
        "steps": 50, "cfg": 3.5, "sampler_name": "euler", "scheduler": "simple",
        "denoise": 0.28, "feather": 5, "noise_mask": True, "force_inpaint": True,
        "bbox_threshold": 0.5, "bbox_dilation": 2, "bbox_crop_factor": 2.0,
        "sam_detection_hint": "center-1", "sam_dilation": 0, "sam_threshold": 0.93,
        "sam_bbox_expansion": 0, "sam_mask_hint_threshold": 0.7,
        "sam_mask_hint_use_negative": "False", "drop_size": 10, "wildcard": "",
        "cycle": 1, "inpaint_model": False, "noise_mask_feather": 5,
        "tiled_encode": False, "tiled_decode": False,
    }}
    graph[REFINED_OUTPUT_NODE] = {"class_type": "SaveImage", "inputs": {
        "images": ["character_detail", 0],
        "filename_prefix": f"OpenGenjutsu/characters/{job_id}/refined"}}
    return graph
