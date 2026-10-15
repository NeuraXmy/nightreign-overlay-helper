"""Small, lazily loaded ONNX CPU classifier; no training dependencies at runtime."""

from __future__ import annotations

import numpy as np
from PIL import Image

from nightreign_overlay.plugins.map_detect.map_info import Position
from nightreign_overlay.plugins.map_detect.resources import get_data_path

# Output 0 is null; numbered training assets start at output 1.
# Sum the probabilities of visual variants of the same building category.
BASE_CLASSES = {
    0: (0,),
    30: (1,),
    38: (2,),
    524: (2,),
    32: (3,),
    34: (4,),
    525: (4,),
    501: (5,),
    500: (6,),
    41: (7, 8),
    510: (7, 8),
    40: (9, 10, 11),
    511: (9, 10, 11),
    37: (12,),
    535: (13,),
    536: (14,),
}


class PoiCnn:
    """Own one reusable CPU session per detector with bounded inference threads."""

    def __init__(self) -> None:
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            get_data_path("poi_cnn/epoch-42.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )

    def predict(self, image: np.ndarray, positions: list[Position]) -> tuple[np.ndarray, np.ndarray]:
        """Crop native 750-map pixels, pad edges, and infer all requested points once."""
        rgb = Image.fromarray(image).convert("RGB")
        crops = [np.asarray(rgb.crop((x - 32, y - 32, x + 32, y + 32))) for x, y in positions]
        batch = np.stack(crops).astype(np.float32).transpose(0, 3, 1, 2) / 255.0
        outputs = self.session.run(["base_logits", "corner_logits"], {"images": batch})
        probabilities = []
        for logits in outputs:
            exp = np.exp(logits - logits.max(axis=1, keepdims=True))
            probabilities.append(exp / exp.sum(axis=1, keepdims=True))
        return probabilities[0], probabilities[1]
