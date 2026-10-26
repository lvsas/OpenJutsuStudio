"""Version-6 FaceDetailer graph extension; never mutates the vendor image output."""
from __future__ import annotations

import copy

REFINED_OUTPUT_NODE = "character_refined"
REFINE_MODEL_ROLES = {"face_detector": "bbox/face_yolov8m.pt", "face_sam": "sam_vit_b_01ec64.pth"}


def append_face_refine(graph, *, seed: int, job_id: str):
    """Append the installed Impact-Pack schema using the donor's actual conditioning."""
    graph = copy.deepcopy(graph)
    graph["character_bbox"] = {"class_type": "UltralyticsDetectorProvider", "inputs": {
        "model_name": REFINE_MODEL_ROLES["face_detector"]}}
    graph["character_sam"] = {"class_type": "SAMLoader", "inputs": {
        "model_name": REFINE_MODEL_ROLES["face_sam"], "device_mode": "AUTO"}}
    graph["character_detail"] = {"class_type": "FaceDetailer", "inputs": {
        "image": ["18:8", 0], "model": ["18:1", 0], "clip": ["18:2", 0],
        "vae": ["18:3", 0], "positive": ["18:4", 0], "negative": ["18:5", 0],
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
