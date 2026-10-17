"""Train position-free HP material and endpoint forests; export runtime-only ONNX."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from skl2onnx import to_onnx
from sklearn.ensemble import RandomForestClassifier
from tests.support.hp_production_evaluation import production_labels
from tests.support.hp_scene_evaluation import scene_geometry
from tests.support.hp_video import VIDEO_ROOT

from nightreign_overlay.plugins.hp_marker.material_features import cap_features, material_features


def train(
    output: Path, *, holdout_blocks: bool, exclude_video: str | None, context_augmentation: bool
) -> None:
    material_x, material_y, cap_x, cap_y = [], [], [], []
    provenance = []
    cap_rng = np.random.default_rng(9)
    for label in production_labels():
        if label["id"] == exclude_video:
            continue
        path = VIDEO_ROOT / label["video"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != label["video_sha256"]:
            raise ValueError(f"Fixture hash mismatch: {path.name}")
        _, view, _ = scene_geometry(label)
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            raise RuntimeError(f"Cannot open {path.name}")
        indices, material_indices = [], []
        outer = label["outer_cap_source_x"] - label["left_cap_source_x"]
        frame_index = 0
        try:
            while True:
                ok, bgr = capture.read()
                if not ok:
                    break
                timestamp = frame_index / label["fps"]
                segment = next(
                    (
                        part
                        for part in label["gt_segments"]
                        if part["source_start_seconds"] <= timestamp < part["source_end_seconds"]
                    ),
                    None,
                )
                selected = frame_index % 8 == 0 and segment is not None
                if holdout_blocks and int(timestamp // 5) % 2:
                    selected = False
                if selected:
                    rgb = cv2.cvtColor(
                        bgr[view.y() : view.y() + view.height(), view.x() : view.x() + view.width()],
                        cv2.COLOR_BGR2RGB,
                    )
                    variants = [rgb]
                    if context_augmentation:
                        # Older fixtures lack two lower context rows. Train the
                        # same reflection used for a clipped normalization view.
                        normalized = cv2.resize(rgb, (rgb.shape[1], 24), interpolation=cv2.INTER_AREA)
                        clipped = normalized.copy()
                        clipped[22:24] = normalized[[20, 19]]
                        variants.append(clipped)
                    for image in variants:
                        features = material_features(image)
                        if features is None:
                            continue
                        endpoint = segment["gt_length_px"]
                        xs = np.arange(len(features))
                        labels = np.where(xs < endpoint, 0, np.where(xs < outer, 1, 2))
                        valid = (abs(xs - endpoint) > 1) & (abs(xs - outer) > 1) & (xs > 6)
                        chosen = np.flatnonzero(valid)[::3]
                        material_x.append(features[chosen])
                        material_y.append(labels[chosen])
                        distance = np.minimum(abs(xs - endpoint), abs(xs - outer))
                        positive = np.flatnonzero(distance <= 1)
                        negative = np.flatnonzero((distance > 4) & (xs > 40) & (xs < len(features) - 20))
                        chosen = np.r_[
                            positive, cap_rng.choice(negative, min(len(negative), 60), replace=False)
                        ]
                        cap_x.append(cap_features(features, chosen))
                        cap_y.append(distance[chosen] <= 1)
                    indices.append(frame_index)
                    material_indices.append(frame_index)
                frame_index += 1
        finally:
            capture.release()
        provenance.append(
            {
                "id": label["id"],
                "source_sha256": label["source_sha256"],
                "fixture_sha256": label["video_sha256"],
                "cap_training_frame_indices": indices,
                "material_training_frame_indices": material_indices,
            }
        )
    x, y = np.concatenate(material_x), np.concatenate(material_y)
    rng = np.random.default_rng(20261017)
    chosen = []
    for cls in range(3):
        indices = np.flatnonzero(y == cls)
        rng.shuffle(indices)
        chosen.extend(indices[:10000])
    chosen = np.array(chosen)
    rng.shuffle(chosen)
    material = RandomForestClassifier(
        n_estimators=100,
        max_depth=18,
        min_samples_leaf=3,
        max_features=14,
        n_jobs=4,
        random_state=20261017,
    ).fit(x[chosen], y[chosen])
    cap = RandomForestClassifier(
        n_estimators=80,
        max_depth=16,
        min_samples_leaf=2,
        max_features=25,
        n_jobs=4,
        class_weight="balanced",
        random_state=9,
    ).fit(np.concatenate(cap_x), np.concatenate(cap_y))
    output.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name, model in (("material_v1", material), ("cap_v1", cap)):
        exported = to_onnx(
            model,
            np.zeros((1, model.n_features_in_), np.float32),
            target_opset=17,
            options={id(model): {"zipmap": False}},
        ).SerializeToString()
        (output / f"{name}.onnx").write_bytes(exported)
        hashes[f"{name}.onnx"] = hashlib.sha256(exported).hexdigest()
    metadata = {
        "feature_version": 1,
        "material_classes": ["usable", "gray", "background"],
        "material_features": 72,
        "cap_features": 360,
        "holdout_alternating_five_second_blocks": holdout_blocks,
        "excluded_video": exclude_video,
        "context_augmentation": context_augmentation,
        "material_training_columns": len(chosen),
        "cap_training_columns": len(np.concatenate(cap_y)),
        "artifacts": hashes,
        "provenance": provenance,
    }
    (output / "training.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + chr(10), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--holdout-blocks", action="store_true")
    parser.add_argument("--exclude-video", choices=[label["id"] for label in production_labels()])
    parser.add_argument("--context-augmentation", action="store_true")
    args = parser.parse_args()
    train(
        args.output,
        holdout_blocks=args.holdout_blocks,
        exclude_video=args.exclude_video,
        context_augmentation=args.context_augmentation,
    )


if __name__ == "__main__":
    main()
