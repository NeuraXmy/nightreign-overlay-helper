import cv2
import numpy as np
from dataclasses import dataclass
from PIL import Image
import time
from PyQt6.QtGui import QPixmap
from mss.base import MSSBase

from src.config import Config
from src.common import get_data_path, get_appdata_path
from src.logger import info, warning, error
from src.detector.utils import grab_region, resize_by_height_keep_aspect_ratio, match_template

@dataclass
class ArtDetectParam:
    art_region: tuple[int] | None = None
    hdr_processing_enabled: bool = True

@dataclass
class ArtDetectResult:
    art_type: str | None = None


class ArtDetector:
    def __init__(self):
        config = Config.get()
        self.art_imgs: dict[str, np.ndarray] = {}
        for art_type in config.art_info.keys():
            img = Image.open(get_data_path(f"icons/art/{art_type}.png")).convert("RGB")
            img = resize_by_height_keep_aspect_ratio(img, config.art_detect_standard_size)
            w, h = img.size
            img = np.array(img)[h//4:h*3//4, w//4:w*3//4]
            self.art_imgs[art_type] = img

    def detect(self, sct: MSSBase, params: ArtDetectParam | None) -> ArtDetectResult:
        if params is None or params.art_region is None:
            return ArtDetectResult()
        config = Config.get()
        ret = ArtDetectResult()

        # 根据参数选择图像处理方式
        processing = 'hdr_to_sdr' if params.hdr_processing_enabled else 'none'
        sc = grab_region(sct, params.art_region, processing=processing).convert("RGB")
        sc = resize_by_height_keep_aspect_ratio(sc, config.art_detect_standard_size)
        sc = np.array(sc)

        best_art_type, best_score = None, 1.0
        for art_type, art_img in self.art_imgs.items():
            match, score = match_template(sc, art_img, config.art_detect_match_scales)
            if score < best_score:
                best_art_type, best_score = art_type, score
            info(f"Art type: {art_type}, score: {score:.4f}")
        
        # 保存用于调试
        cv2.imwrite(get_appdata_path("last_art_sc.png"), cv2.cvtColor(sc, cv2.COLOR_RGB2BGR))

        if best_score < config.art_detect_threshold:
            ret.art_type = best_art_type
            info(f"Detected art type: {best_art_type}, score: {best_score:.4f}")
        else:
            info(f"No art detected, best score: {best_score:.4f}")

        return ret
    


