import cv2
import numpy as np
from dataclasses import dataclass
from PIL import Image
import time
from mss.base import MSSBase
import yaml

from src.config import Config
from src.logger import info, warning, error, debug
from src.common import get_data_path
from src.detector.utils import resize_by_height_keep_aspect_ratio, grab_region


def get_image_mask(image: Image.Image) -> np.ndarray:
    config = Config.get()
    image_np = np.array(image)
    image_bgr = cv2.cvtColor(image_np, cv2.COLOR_RGB2BGR)
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    lower_white = np.array(config.mask_lower_white)
    upper_white = np.array(config.mask_upper_white)
    mask = cv2.inRange(hsv, lower_white, upper_white)
    # cv2.imwrite(f"sandbox/debug_hsv_mask.png", mask)
    return mask

def match_mask(image: np.ndarray, template: np.ndarray) -> float:
    t = time.time()
    scale_range = np.linspace(*Config.get().scale_range, endpoint=True)
    score = float('inf')
    for scale in scale_range:
        w, h = template.shape[::-1]
        resized_template = cv2.resize(template, (int(w * scale), int(h * scale)))
        if resized_template.shape[0] > image.shape[0] or resized_template.shape[1] > image.shape[1]:
            continue
        res = cv2.matchTemplate(image, resized_template, cv2.TM_SQDIFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
        score = min(score, min_val)
    # print("match mask score: ", score)
    # print("match mask time: ", time.time() - t)
    return score


@dataclass
class DayDetectParam:
    day1_region: tuple[int] | None = None
    lang: str | None = None
    hdr_processing_enabled: bool = False

@dataclass
class DayDetectResult:
    start_day1: bool = False
    start_day2: bool = False
    start_day3: bool = False
    score_day1: float = None
    score_day2: float = None
    score_day3: float = None


@dataclass
class DayTempalte:
    lang: str
    day1_mask: np.ndarray
    day2_mask: np.ndarray
    day3_mask: np.ndarray
    day2_w_ratio: float
    day3_w_ratio: float


class DayDetector:
    def __init__(self):
        config = Config.get()
        self.templates: dict[str, DayTempalte] = {}
        for lang in config.dayx_detect_langs.keys():
            day1_image = Image.open(get_data_path(f"day_template/{lang}_1.png")).convert("RGB")
            day2_image = Image.open(get_data_path(f"day_template/{lang}_2.png")).convert("RGB")
            day3_image = Image.open(get_data_path(f"day_template/{lang}_3.png")).convert("RGB")
            day1_mask = get_image_mask(resize_by_height_keep_aspect_ratio(day1_image, config.template_standard_height))
            day2_mask = get_image_mask(resize_by_height_keep_aspect_ratio(day2_image, config.template_standard_height))
            day3_mask = get_image_mask(resize_by_height_keep_aspect_ratio(day3_image, config.template_standard_height))
            # cv2.imwrite(f"sandbox/debug_day1_{lang}.png", day1_mask)
            # cv2.imwrite(f"sandbox/debug_day2_{lang}.png", day2_mask)
            # cv2.imwrite(f"sandbox/debug_day3_{lang}.png", day3_mask)
            template = DayTempalte(
                lang=lang,
                day1_mask=day1_mask, day2_mask=day2_mask, day3_mask=day3_mask,
                day2_w_ratio=day2_mask.shape[1] / day1_mask.shape[1],
                day3_w_ratio=day3_mask.shape[1] / day1_mask.shape[1],
            )
            self.templates[lang] = template

    def match(self, sct: MSSBase, template: DayTempalte, params: DayDetectParam) -> tuple[bool, float]:
        try:
            config = Config.get()
            t = time.time()
            day1_region = params.day1_region
            x, y, w, h = day1_region
            cx, cy = x + w // 2, y + h // 2
            day2_w = int(w * template.day2_w_ratio)
            day2_region = (cx - day2_w // 2, cy - h // 2, day2_w, h)
            day3_w = int(w * template.day3_w_ratio)
            day3_region = (cx - day3_w // 2, cy - h // 2, day3_w, h)
            # 根据参数选择图像处理方式
            processing = 'hdr_to_sdr' if params.hdr_processing_enabled else 'none'
            sc = grab_region(sct, day3_region, processing=processing)
            def match_region(region: tuple[int], template_mask: np.ndarray) -> float:
                region = (
                    region[0] - day3_region[0], 
                    region[1] - day3_region[1], 
                    region[0] - day3_region[0] + region[2], 
                    region[1] - day3_region[1] + region[3]
                )
                img = sc.crop(region)
                img = resize_by_height_keep_aspect_ratio(img, config.template_standard_height)
                img_mask = get_image_mask(img)
                return match_mask(img_mask, template_mask)
            score_day1 = match_region(day1_region, template.day1_mask)
            score_day2 = match_region(day2_region, template.day2_mask)
            score_day3 = match_region(day3_region, template.day3_mask)
            debug(f"detect dayx time: {time.time() - t} lang: {template.lang} score: {score_day1:.2f}, {score_day2:.2f}, {score_day3:.2f}")
            return score_day1, score_day2, score_day3
        except Exception as e:
            error(f"Detect dayx error")
            return float('inf'), float('inf'), float('inf')

    def detect(self, sct: MSSBase, params: DayDetectParam | None) -> DayDetectResult:
        ret = DayDetectResult()
        config = Config.get()
        if params is None or params.day1_region is None:
            return ret
        template = self.templates[params.lang]
        score_day1, score_day2, score_day3 = self.match(sct, template, params)
        ret.score_day1 = score_day1
        ret.score_day2 = score_day2
        ret.score_day3 = score_day3
        if score_day1 < config.dayx_score_threshold: ret.start_day1 = True
        if score_day2 < config.dayx_score_threshold: ret.start_day2 = True
        if score_day3 < config.dayx_score_threshold: ret.start_day3 = True
        return ret