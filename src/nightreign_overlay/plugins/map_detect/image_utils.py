"""Map image drawing, template matching and SIFT alignment."""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from nightreign_overlay.plugins.map_detect.resources import get_data_path

DEFAULT_FONT_PATH = get_data_path("fonts/SourceHanSansSC-Normal.otf")
font_cache: dict[str, ImageFont.FreeTypeFont] = {}


def paste_cv2(img1: np.ndarray, img2: np.ndarray, pos: tuple[int, int]) -> None:
    x, y = pos
    h, w = img2.shape[0], img2.shape[1]
    img1[y : y + h, x : x + w] = img2


def get_font(size: int, path: str = DEFAULT_FONT_PATH) -> ImageFont.FreeTypeFont:
    key = f"{path}-{size}"
    if key not in font_cache:
        font_cache[key] = ImageFont.truetype(path, size)
    return font_cache[key]


def get_text_size(font: ImageFont.FreeTypeFont, text: str) -> tuple[int, int]:
    return font.getbbox(text)[2:4]


def draw_icon(
    img: Image.Image, pos: tuple[int, int], icon: Image.Image, size: tuple[int, int] | None = None
) -> None:
    if size is None:
        size = icon.size
    icon = icon.resize(size, resample=Image.Resampling.BICUBIC)
    img.alpha_composite(icon, (pos[0] - size[0] // 2, pos[1] - size[1] // 2))


def draw_text(
    img: Image.Image,
    pos: tuple[int, int],
    text: str,
    size: int,
    color: tuple[int, int, int, int],
    outline_width: int = 0,
    outline_color: tuple[int, int, int, int] = (0, 0, 0, 255),
    align: str = "c",
    *,
    width_scale: float = 1.0,
) -> None:
    """Draw outlined text, optionally compressing only its width around the same anchor."""
    assert align in ("lb", "c", "lt")
    if text is None:
        text = "null"
    font = get_font(size)
    text_width, text_height = get_text_size(font, text)
    scaled_width = round(text_width * width_scale)
    if align == "lb":
        pos = (pos[0] + scaled_width // 2, pos[1] - text_height // 2)
    elif align == "lt":
        pos = (pos[0] + scaled_width // 2, pos[1] + text_height // 2)
    text_pos = (pos[0] - scaled_width // 2, pos[1] - text_height // 2)
    if width_scale == 1.0:
        ImageDraw.Draw(img).text(
            text_pos,
            text,
            font=font,
            fill=color,
            stroke_width=outline_width,
            stroke_fill=outline_color,
        )
        return

    # Include glyph bearings and the entire outline before resizing, even near map edges.
    left, top, right, bottom = font.getbbox(text, stroke_width=outline_width)
    if right <= left or bottom <= top:
        return
    label = Image.new("RGBA", (right - left, bottom - top))
    ImageDraw.Draw(label).text(
        (-left, -top),
        text,
        font=font,
        fill=color,
        stroke_width=outline_width,
        stroke_fill=outline_color,
    )
    label = label.resize(
        (max(1, round(label.width * width_scale)), label.height),
        resample=Image.Resampling.LANCZOS,
    )
    img.alpha_composite(label, (text_pos[0] + round(left * width_scale), text_pos[1] + top))


def match_template(
    image: np.ndarray, template: np.ndarray, scales: tuple[float, float, int], mask: np.ndarray | None = None
) -> tuple[tuple[tuple[int, int], int, int, float] | None, float]:
    best_match = None
    best_val = float("inf")
    for scale in np.linspace(scales[0], scales[1], num=scales[2], endpoint=True):
        resized_template = cv2.resize(
            template, (int(template.shape[1] * scale), int(template.shape[0] * scale))
        )
        if resized_template.shape[0] > image.shape[0] or resized_template.shape[1] > image.shape[1]:
            continue
        if mask is not None:
            # 注意：cv2.matchTemplate 的 mask 参数对 TM_SQDIFF_NORMED 静默无效，
            # 只对 TM_SQDIFF 生效。这里用 TM_SQDIFF + mask，再按有效像素数归一化到 [0,1]，
            # 数值尺度与 TM_SQDIFF_NORMED 接近，便于复用原有阈值。
            resized_mask = cv2.resize(mask, (resized_template.shape[1], resized_template.shape[0]))
            result = cv2.matchTemplate(image, resized_template, cv2.TM_SQDIFF, resized_mask)
            n_active = max(1, np.count_nonzero(resized_mask) * resized_template.shape[2])
            result = result / (n_active * 255.0 * 255.0)
        else:
            result = cv2.matchTemplate(image, resized_template, cv2.TM_SQDIFF_NORMED)
        min_val, _max_val, min_loc, _max_loc = cv2.minMaxLoc(result)
        if min_val < best_val:
            best_val = min_val
            best_match = (min_loc, resized_template.shape[1], resized_template.shape[0], scale)
    return best_match, best_val


def align_image(img: np.ndarray, target: np.ndarray, region: tuple[int, int, int, int]) -> np.ndarray:
    """
    使用 SIFT 特征点匹配对齐两张图像。
    仅使用 region 区域内的图像进行特征点检测和匹配，返回对齐后的整张图像。

    Args:
        img: 待变换的图像 (图A)
        target: 对齐基准图 (图B)
        region: (x, y, w, h) 指定用于匹配的区域坐标

    Returns:
        np.ndarray: 对齐后的图像，大小与 target 一致
    """
    x, y, w, h = region

    roi_img = img[y : y + h, x : x + w]
    roi_target = target[y : y + h, x : x + w]

    gray_img = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
    gray_target = cv2.cvtColor(roi_target, cv2.COLOR_BGR2GRAY)

    sift = cv2.SIFT_create()
    kp_img, des_img = sift.detectAndCompute(gray_img, None)
    kp_target, des_target = sift.detectAndCompute(gray_target, None)

    if des_img is None or des_target is None:
        raise ValueError("align_image: No features found in region.")

    index_params = dict(algorithm=1, trees=5)  # FLANN_INDEX_KDTREE = 1
    search_params = dict(checks=50)
    flann = cv2.FlannBasedMatcher(index_params, search_params)
    matches = flann.knnMatch(des_img, des_target, k=2)
    good_matches = []
    for m, n in matches:
        if m.distance < 0.7 * n.distance:
            good_matches.append(m)

    if len(good_matches) < 4:
        raise ValueError(f"align_image: Not enough matches found ({len(good_matches)}).")

    src_pts = np.float32([kp_img[m.queryIdx].pt for m in good_matches]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp_target[m.trainIdx].pt for m in good_matches]).reshape(-1, 1, 2)

    src_pts[:, 0, 0] += x
    src_pts[:, 0, 1] += y
    dst_pts[:, 0, 0] += x
    dst_pts[:, 0, 1] += y

    matrix, _mask = cv2.estimateAffinePartial2D(src_pts, dst_pts, method=cv2.RANSAC)

    if matrix is not None:
        h_target, w_target = target.shape[:2]
        aligned_img = cv2.warpAffine(
            img,
            matrix,
            (w_target, h_target),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
        return aligned_img
    else:
        raise ValueError("align_image: Could not compute affine transformation matrix.")
