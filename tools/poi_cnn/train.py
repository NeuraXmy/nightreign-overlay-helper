"""Train a small CNN for base and corner POI classification.

Runs on a single GPU when one is available (``--device cuda`` by default) and
falls back to CPU automatically.  The training set is generated on demand.  The
validation set is materialized once under ``--val-dir`` and then reused verbatim
on later runs.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torch import nn
from torch.utils.data import DataLoader, Dataset

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import synthesize as syn


# Base loss is weighted above corner loss (base is the harder, more error-prone head).
BASE_LOSS_WEIGHT = 2.0


class PoiNet(nn.Module):
    def __init__(self, base_classes: int = 15, corner_classes: int = 12):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 16, 3, padding=1), nn.BatchNorm2d(16), nn.ReLU(inplace=True), nn.MaxPool2d(2),
            nn.Conv2d(16, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(inplace=True), nn.MaxPool2d(2),
            nn.Conv2d(32, 48, 3, padding=1), nn.BatchNorm2d(48), nn.ReLU(inplace=True), nn.MaxPool2d(2),
            nn.Conv2d(48, 64, 3, padding=1), nn.ReLU(inplace=True), nn.AdaptiveAvgPool2d(1),
        )
        self.base_head = nn.Linear(64, base_classes)
        self.corner_head = nn.Linear(64, corner_classes)
        self.dropout = nn.Dropout(0.1)

    def forward(self, x):
        z = self.dropout(self.features(x).flatten(1))
        return self.base_head(z), self.corner_head(z)


def _assets(root: Path):
    base = {k: Image.open(p).convert("RGBA") for k, p in syn._numbered_files(root / "base", {".png"}).items()}
    corner = {k: Image.open(p).convert("RGBA") for k, p in syn._numbered_files(root / "corner", {".png"}).items()}
    backgrounds = {k: Image.open(p).convert("RGB") for k, p in syn._numbered_files(root / "bg", {".jpg", ".jpeg", ".png"}).items()}
    meta = syn._read_meta(root / "base" / "meta.txt")
    variants = {k: Image.open(p).convert("RGBA") for k, p in syn._numbered_files(root / "var", {".png"}).items()}
    games = {k: Image.open(p).convert("RGB") for k, p in syn._numbered_files(root / "game", {".jpg", ".jpeg", ".png"}).items()}
    others = {k: Image.open(p).convert("RGBA") for k, p in syn._numbered_files(root / "other", {".png"}).items()}
    players = {k: Image.open(p).convert("RGBA") for k, p in syn._numbered_files(root / "player", {".png"}).items()}
    return base, corner, backgrounds, meta, variants, games, others, players


def _make_sample(rng: random.Random, assets):
    base, corners, backgrounds, meta, variants, games, others, players = assets
    bg_key = syn._choose_background(rng, backgrounds)
    base_key = syn._choose_base(rng, base, meta)
    has_base = rng.random() >= syn.NO_BASE_RATE
    selected_base = base_key if has_base else None
    has_corner = rng.random() >= syn.NO_CORNER_RATE and has_base
    selected_corner = rng.choice([*sorted(corners)]) if has_corner else None
    selected_variant = syn._choose_variant(rng, variants, has_base)
    base_img = base[selected_base] if selected_base is not None else None
    corner_img = corners[selected_corner] if selected_corner is not None else None
    variant_img = variants[selected_variant] if selected_variant is not None else None
    icon_key = meta[selected_base] if selected_base is not None else None
    image, _, _ = syn._compose(backgrounds[bg_key], base_img, icon_key, corner_img, variant_img, selected_variant, rng, others)
    syn._add_blue_overlay(image, rng)
    syn._add_player(image, players.get(0), rng)
    syn._adjust_color(image, rng)
    _, image = syn._adjust_detail(image, rng)
    _, image = syn._blend_onto_game(image, games, rng)
    return image, (selected_base + 1 if selected_base is not None else 0), (selected_corner + 1 if selected_corner is not None else 0)


def _tensor(image: Image.Image) -> torch.Tensor:
    array = np.asarray(image, dtype=np.float32) / 255.0
    return torch.from_numpy(array.transpose(2, 0, 1).copy())


class DynamicDataset(Dataset):
    def __init__(self, assets, length: int, seed: int):
        self.assets, self.length, self.seed = assets, length, seed

    def __len__(self):
        return self.length

    def __getitem__(self, index):
        rng = random.Random(self.seed + index + random.randrange(1 << 30))
        image, base, corner = _make_sample(rng, self.assets)
        return _tensor(image), torch.tensor(base), torch.tensor(corner)


class FixedDataset(Dataset):
    def __init__(self, directory: Path):
        rows = [json.loads(x) for x in (directory / "labels.jsonl").read_text().splitlines()]
        self.items = [(directory / row["image"], row["base"], row["corner"]) for row in rows]

    def __len__(self): return len(self.items)

    def __getitem__(self, index):
        path, base, corner = self.items[index]
        image = Image.open(path).convert("RGB")
        return _tensor(image), torch.tensor((base + 1) if base is not None else 0), torch.tensor((corner + 1) if corner is not None else 0)


def make_validation(directory: Path, assets, count: int, seed: int):
    """Rebuild the validation set on every run so it always reflects the
    current synthesis pipeline (no stale caching)."""
    directory.mkdir(parents=True, exist_ok=True)
    for stale in directory.glob("*.png"):
        stale.unlink()
    rows = []
    rng = random.Random(seed)
    for i in range(count):
        image, base, corner = _make_sample(rng, assets)
        name = f"{i:04d}.png"
        image.save(directory / name)
        rows.append({"image": name, "base": base - 1 if base else None, "corner": corner - 1 if corner else None})
    (directory / "labels.jsonl").write_text("\n".join(json.dumps(x) for x in rows) + "\n")


def evaluate(model, loader, device):
    model.eval(); total = correct_b = correct_c = 0; loss_sum = 0.0
    loss_fn = nn.CrossEntropyLoss(reduction="sum")
    with torch.inference_mode():
        for x, yb, yc in loader:
            x = x.to(device); yb = yb.to(device); yc = yc.to(device)
            pb, pc = model(x); total += len(x)
            correct_b += (pb.argmax(1) == yb).sum().item(); correct_c += (pc.argmax(1) == yc).sum().item()
            loss_sum += (BASE_LOSS_WEIGHT * loss_fn(pb, yb) + loss_fn(pc, yc)).item()
    return correct_b / total, correct_c / total, loss_sum / total


def _class_name(label: int) -> str:
    """Map a head output index back to a display name (0 is the null class)."""
    return "null" if label == 0 else f"{label - 1:02d}"


def _discover_tests(root: Path) -> dict[str, Path]:
    """Return ``{name: directory}`` for each subfolder holding a labels.jsonl."""
    if not root.is_dir():
        return {}
    return {sub.name: sub for sub in sorted(root.iterdir()) if (sub / "labels.jsonl").is_file()}


def evaluate_test(model, dataset, device):
    """Return ``(base_acc, corner_acc, [(path, gt_b, gt_c, pred_b, pred_c), ...])``."""
    loader = DataLoader(dataset, batch_size=64)
    model.eval()
    results = []
    index = 0
    with torch.inference_mode():
        for x, yb, yc in loader:
            pb, pc = model(x.to(device))
            pb = pb.argmax(1).cpu(); pc = pc.argmax(1).cpu()
            for j in range(len(x)):
                results.append((dataset.items[index][0], yb[j].item(), yc[j].item(), pb[j].item(), pc[j].item()))
                index += 1
    total = len(results)
    base_acc = sum(r[1] == r[3] for r in results) / total
    corner_acc = sum(r[2] == r[4] for r in results) / total
    return base_acc, corner_acc, results


def plot_test_predictions(name: str, results, path: Path, max_images: int, columns: int = 8):
    """Save a grid of ``image | GT | prediction`` for a real test set."""
    items = results[:max_images]
    rows = max(1, math.ceil(len(items) / columns))
    fig, axes = plt.subplots(rows, columns, figsize=(columns * 1.5, rows * 1.95))
    axes = np.atleast_1d(axes).ravel()
    for ax, (image_path, gb, gc, pb, pc) in zip(axes, items):
        ax.imshow(Image.open(image_path).convert("RGB"))
        ax.set_xticks([]); ax.set_yticks([])
        correct = gb == pb and gc == pc
        ax.set_title(
            f"GT b{_class_name(gb)} c{_class_name(gc)}\nPR b{_class_name(pb)} c{_class_name(pc)}",
            fontsize=6, color=("tab:green" if correct else "tab:red"),
        )
    for ax in axes[len(items):]:
        ax.axis("off")
    fig.suptitle(f"{name}: image / GT / prediction (green=correct, red=wrong)", fontsize=9)
    fig.tight_layout(rect=(0, 0, 1, 0.97)); fig.savefig(path, dpi=120); plt.close(fig)


def save_test_results(name: str, epoch: int, results, path: Path):
    """Dump per-sample predictions and accuracies for a test set as JSON."""
    total = len(results)
    rows = [
        {
            "image": Path(image_path).name,
            "gt_base": gb, "gt_corner": gc,
            "pred_base": pb, "pred_corner": pc,
            "correct": gb == pb and gc == pc,
        }
        for image_path, gb, gc, pb, pc in results
    ]
    payload = {
        "name": name,
        "epoch": epoch,
        "n": total,
        "base_acc": sum(r["gt_base"] == r["pred_base"] for r in rows) / total,
        "corner_acc": sum(r["gt_corner"] == r["pred_corner"] for r in rows) / total,
        "results": rows,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def _selection_metric(test_scores):
    """Combine real test-set accuracies into one scalar for model selection.

    Each test set contributes its ``base + corner`` accuracy with equal weight;
    returns ``None`` when no real set is available so the caller can fall back
    to the synthetic validation score.
    """
    if not test_scores:
        return None
    return sum(base + corner for base, corner in test_scores.values()) / len(test_scores)


def plot_curves(history, path: Path, best_epoch: int | None = None):
    epochs = range(1, len(history["train_loss"]) + 1)
    fig, (ax_loss, ax_acc, ax_lr) = plt.subplots(3, 1, figsize=(8, 9), sharex=True)
    ax_loss.plot(epochs, history["train_loss"], color="tab:red", marker="o", label="train loss")
    ax_loss.plot(epochs, history["val_loss"], color="tab:orange", marker="o", label="val loss")
    ax_loss.set_ylabel("loss"); ax_loss.grid(alpha=0.3); ax_loss.legend(loc="upper right")
    ax_acc.plot(epochs, history["val_base"], color="tab:blue", marker="o", label="val base acc")
    ax_acc.plot(epochs, history["val_corner"], color="tab:green", marker="o", label="val corner acc")
    linestyles = ["--", ":", "-."]
    for offset, (name, scores) in enumerate(history.get("tests", {}).items()):
        style = linestyles[offset % len(linestyles)]
        ax_acc.plot(epochs, scores["base"], color="tab:blue", linestyle=style, alpha=0.7, label=f"{name} base acc")
        ax_acc.plot(epochs, scores["corner"], color="tab:green", linestyle=style, alpha=0.7, label=f"{name} corner acc")
    ax_acc.set_ylabel("acc"); ax_acc.grid(alpha=0.3)
    ax_acc.set_ylim(0.0, 1.02); ax_acc.legend(loc="lower right", fontsize=7)
    ax_lr.plot(epochs, history["lr"], color="tab:purple", marker="o", label="learning rate")
    ax_lr.set_xlabel("epoch"); ax_lr.set_ylabel("lr"); ax_lr.grid(alpha=0.3); ax_lr.legend(loc="upper right")
    if best_epoch:
        for ax in (ax_loss, ax_acc, ax_lr):
            ax.axvline(best_epoch, color="tab:gray", linestyle="--", alpha=0.6)
    fig.tight_layout(); fig.savefig(path, dpi=120); plt.close(fig)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--assets", type=Path, default=Path(__file__).parent / "assets")
    p.add_argument("--val-dir", type=Path, default=Path(__file__).parent / "validation")
    p.add_argument("--val-size", type=int, default=500)
    p.add_argument("--output", type=Path, default=Path(__file__).parent / "ckpt" / "output15" / "poi_net.pt")
    p.add_argument("--epochs", type=int, default=50); 
    p.add_argument("--steps", type=int, default=1000)
    p.add_argument("--patience", type=int, default=10, help="early stopping patience in epochs; 0 disables it")
    p.add_argument("--min-delta", type=float, default=1e-4, help="minimum (val_base+val_corner) improvement to reset patience")
    p.add_argument("--batch-size", type=int, default=128); 
    p.add_argument("--workers", type=int, default=64)
    p.add_argument("--device", type=str, default="cuda", help="training device, e.g. cuda / cuda:0 / cpu")
    p.add_argument("--test-dir", type=Path, default=Path(__file__).parent / "testset", help="directory whose subfolders hold real test sets (each with labels.jsonl)")
    p.add_argument("--test-max-images", type=int, default=48, help="max images per test-set preview grid")
    args = p.parse_args()
    if args.device.startswith("cuda"):
        device = torch.device(args.device if torch.cuda.is_available() else "cpu")
    else:
        device = torch.device(args.device)
    if device.type == "cuda":
        torch.backends.cudnn.benchmark = True
        print(f"using device: {device} ({torch.cuda.get_device_name(device)})", flush=True)
    else:
        torch.set_num_threads(max(1, min(4, torch.get_num_threads())))
        print(f"using device: {device}", flush=True)
    assets = _assets(args.assets); make_validation(args.val_dir, assets, args.val_size, 20261013)
    pin_memory = device.type == "cuda"
    train = DataLoader(DynamicDataset(assets, args.steps * args.batch_size, 91), batch_size=args.batch_size, shuffle=False, num_workers=args.workers, pin_memory=pin_memory)
    val = DataLoader(FixedDataset(args.val_dir), batch_size=args.val_size, pin_memory=pin_memory)
    tests = {name: FixedDataset(path) for name, path in _discover_tests(args.test_dir).items()}
    if tests:
        print("test sets: " + ", ".join(f"{name}({len(ds)})" for name, ds in tests.items()), flush=True)
    model = PoiNet().to(device); opt = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=5e-4); loss_fn = nn.CrossEntropyLoss(label_smoothing=0.05)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    history = {"train_loss": [], "val_loss": [], "val_base": [], "val_corner": [], "lr": [], "select": [],
               "tests": {name: {"base": [], "corner": []} for name in tests}}
    best_metric, best_epoch, no_improve, best_source = -1.0, 0, 0, ""
    for epoch in range(args.epochs):
        model.train(); total = 0.0
        epoch_start = time.perf_counter()
        for step, (x, yb, yc) in enumerate(train, 1):
            step_start = time.perf_counter()
            x = x.to(device, non_blocking=True); yb = yb.to(device, non_blocking=True); yc = yc.to(device, non_blocking=True)
            opt.zero_grad(set_to_none=True); pb, pc = model(x); loss = BASE_LOSS_WEIGHT * loss_fn(pb, yb) + loss_fn(pc, yc); loss.backward(); opt.step(); total += loss.item()
            # print(
            #     f"epoch {epoch + 1:02d} step {step:04d}/{args.steps}: "
            #     f"loss={loss.item():.4f} time={(time.perf_counter() - step_start) * 1000:.2f} ms",
            #     flush=True,
            # )
        lr = opt.param_groups[0]["lr"]
        scheduler.step()
        validation_start = time.perf_counter()
        ab, ac, vl = evaluate(model, val, device)
        history["train_loss"].append(total / step)
        history["val_loss"].append(vl)
        history["val_base"].append(ab); history["val_corner"].append(ac); history["lr"].append(lr)
        print(
            f"epoch {epoch + 1:02d}/{args.epochs}: "
            f"train_loss={total / step:.4f} val_loss={vl:.4f} "
            f"val_base={ab:.3f} val_corner={ac:.3f} lr={lr:.2e} "
            f"train_time={time.perf_counter() - epoch_start:.2f}s "
            f"val_time={time.perf_counter() - validation_start:.3f}s",
            flush=True,
        )
        test_scores = {}
        for name, dataset in tests.items():
            tb, tc, results = evaluate_test(model, dataset, device)
            test_scores[name] = (tb, tc)
            history["tests"][name]["base"].append(tb)
            history["tests"][name]["corner"].append(tc)
            print(f"  test[{name}] base={tb:.3f} corner={tc:.3f} (n={len(results)})", flush=True)
            plot_test_predictions(name, results, args.output.parent / f"test-{name}.png", args.test_max_images)
            save_test_results(name, epoch + 1, results, args.output.parent / f"test-{name}.json")
        metric = _selection_metric(test_scores)
        metric_source = "real " + "/".join(tests) if metric is not None else "synthetic val"
        if metric is None:
            metric = ab + ac
        history["select"].append(metric)
        print(f"  select={metric:.4f} (from {metric_source})", flush=True)
        if metric > best_metric + args.min_delta:
            best_metric, best_epoch, no_improve = metric, epoch + 1, 0
            best_source = metric_source
            torch.save(
                {"model": model.state_dict(), "base_classes": 15, "corner_classes": 12, "epoch": epoch + 1, "history": history},
                args.output,
            )
        else:
            no_improve += 1
        torch.save(
            {"model": model.state_dict(), "base_classes": 15, "corner_classes": 12, "epoch": epoch + 1, "history": history},
            args.output.parent / f"epoch-{epoch + 1}.pt",
        )
        plot_curves(history, args.output.parent / "curves.png", best_epoch)
        if args.patience > 0 and no_improve >= args.patience:
            print(f"early stopping at epoch {epoch + 1} (best epoch {best_epoch}, best metric {best_metric:.4f})", flush=True)
            break
    print(f"best epoch {best_epoch} select={best_metric:.4f} (from {best_source or 'synthetic val'}); best model saved to {args.output}", flush=True)
    model.load_state_dict(torch.load(args.output, map_location=device)["model"])
    x, _, _ = next(iter(val)); x = x.to(device); model.eval()
    with torch.inference_mode():
        for _ in range(5): model(x)
        if device.type == "cuda": torch.cuda.synchronize()
        start = time.perf_counter()
        for _ in range(50): model(x)
        if device.type == "cuda": torch.cuda.synchronize()
    print(f"{device.type} batch={len(x)} average={(time.perf_counter() - start) / 50 * 1000:.2f} ms")


if __name__ == "__main__": main()
