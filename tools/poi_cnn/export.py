"""Export a trusted PoiNet checkpoint with dynamic batches for CPU deployment."""

from __future__ import annotations

import argparse
import inspect
from pathlib import Path

import onnx
import torch
from train import PoiNet

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=Path(__file__).parent / "epoch-42.pt")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "src/nightreign_overlay/plugins/map_detect/data/poi_cnn/epoch-42.onnx",
    )
    args = parser.parse_args()
    torch.set_num_threads(2)
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    model = PoiNet(checkpoint["base_classes"], checkpoint["corner_classes"]).eval()
    model.load_state_dict(checkpoint["model"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    exporter_options = (
        {"dynamo": False} if "dynamo" in inspect.signature(torch.onnx.export).parameters else {}
    )
    torch.onnx.export(
        model,
        torch.zeros(2, 3, 64, 64),
        str(args.output),
        input_names=["images"],
        output_names=["base_logits", "corner_logits"],
        dynamic_axes={"images": {0: "batch"}, "base_logits": {0: "batch"}, "corner_logits": {0: "batch"}},
        opset_version=17,
        **exporter_options,
    )
    onnx.checker.check_model(onnx.load(args.output))
    print(f"Exported {args.output}; ONNX structure validated (dynamic batch, opset 17)")


if __name__ == "__main__":
    main()
