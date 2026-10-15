"""Faithful legacy full-map, terrain, nightlord, POI recognition and complete overlay rendering."""

from __future__ import annotations

import gc
import os
import random
import time
from dataclasses import dataclass, field
from enum import Enum

import cv2
import numpy as np
from PIL import Image

from nightreign_overlay.core.log import get_logger
from nightreign_overlay.plugins.map_detect.config import MapDetectionSettings
from nightreign_overlay.plugins.map_detect.image_utils import (
    align_image,
    draw_icon,
    draw_text,
    match_template,
    paste_cv2,
)
from nightreign_overlay.plugins.map_detect.localization import I18N_DIR, load_names, rendering_translator
from nightreign_overlay.plugins.map_detect.map_info import (
    STD_MAP_SIZE,
    Construct,
    MapInfo,
    MapPattern,
    Position,
    load_map_info,
)
from nightreign_overlay.plugins.map_detect.poi_cnn import BASE_CLASSES, PoiCnn
from nightreign_overlay.plugins.map_detect.resources import get_appdata_path, get_data_path

log = get_logger(__name__)

CV2_RESIZE_METHOD = cv2.INTER_CUBIC
PIL_RESAMPLE_METHOD = Image.Resampling.BICUBIC


def open_pil_image(path: str, size: tuple[int, int] | None = None) -> Image.Image:
    path = get_data_path(path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Image file not found: {path}")
    image = Image.open(path).convert("RGBA")
    image.load()
    if size is not None:
        image = image.resize(size, resample=PIL_RESAMPLE_METHOD)
    return image


def open_cv2_image(path: str, size: tuple[int, int] | None = None) -> np.ndarray:
    path = get_data_path(path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Image file not found: {path}")
    image = cv2.cvtColor(cv2.imread(path), cv2.COLOR_BGR2RGB)
    if size is not None:
        image = cv2.resize(image, size, interpolation=CV2_RESIZE_METHOD)
    return image


CHECK_FULL_MAP_STD_SIZE = (100, 100)

MATCH_EARTH_SHIFTING_SIZE = (100, 100)
MATCH_EARTH_SHIFTING_REGION = (
    int(MATCH_EARTH_SHIFTING_SIZE[0] * 0.2),
    int(MATCH_EARTH_SHIFTING_SIZE[1] * 0.2),
    int(MATCH_EARTH_SHIFTING_SIZE[0] * 0.6),
    int(MATCH_EARTH_SHIFTING_SIZE[1] * 0.6),
)
MATCH_EARTH_SHIFTING_OFFSET_AND_STRIDE = (5, 1)
MATCH_EARTH_SHIFTING_SCALES = (0.95, 1.05, 7)

MAP_BGS = {i: open_cv2_image(f"maps/{i}.jpg") for i in range(6)}
MAG_BG_FOR_POI_MATCH_INDEX_MAP = {
    # 除了大空洞，其他使用普通地图背景进行POI匹配（因为特殊地形内不会匹配，所以没有问题）
    0: 0,
    1: 0,
    2: 0,
    3: 0,
    4: 4,
    5: 0,
}

MATCH_NIGHTLORD_SIZE = (300, 300)
NIGHTLORD_ICONS = {i: open_pil_image(f"icons/nightlord/{i}.png") for i in range(10)}
EVERNIGHT_NIGHTLORD_ICONS = {i: open_pil_image(f"icons/nightlord/e{i}.png") for i in range(9)}
UNKNOWN_NIGHTLORD_ICON = open_pil_image("icons/nightlord/unk.png")
NIGHTLORD_ICON_BG = open_pil_image("icons/nightlord/bg.png")
MATCH_NIGHTLORD_SCALES = (0.9, 1.1, 7)

POI_ICON_SCALE = {
    30: 0.35,
    32: 0.5,
    34: 0.4,
    37: 0.4,
    38: 0.3,
    40: 0.4,
    41: 0.38,
    510: 0.38,
    511: 0.4,
    500: 0.15,
    501: 0.2,
    524: 0.3,
    525: 0.4,
    535: 0.15,
    536: 0.18,
}
POI_ICON_OFFSET = {
    500: (0, -3),
    501: (0, 3),
    535: (-3, -3),
    536: (0, -2),
}
POI_ICONS = {ctype: open_pil_image(f"icons/construct/{ctype}.png") for ctype in POI_ICON_SCALE}
STD_POI_SIZE = (45, 45)


class Attribute(Enum):
    FIRE = 0
    MAGIC = 1
    THUNDER = 2
    HOLY = 3


class Condition(Enum):
    BLEED = 0
    FROST = 1
    DEATH = 2
    FRENZY = 3
    CORRUPTION = 4
    POISON = 5
    SLEEP = 6


ATTRIBUTE_IMAGES = {
    k: open_pil_image(f"icons/attribute/{k.value}.png") for k in Attribute.__members__.values()
}
CONDITION_IMAGES = {
    k: open_pil_image(f"icons/condition/{k.value}.png") for k in Condition.__members__.values()
}
SUBICON_IMAGES = {**ATTRIBUTE_IMAGES, **CONDITION_IMAGES}

CTYPE_SUBICON_MAP: dict[int, Attribute | Condition] = {
    30301: Attribute.MAGIC,  # 结晶人要塞-魔
    32101: Attribute.FIRE,  # 红狮子营地-火
    32102: Attribute.THUNDER,  # 骑士营地-雷
    32200: Attribute.FIRE,  # 战车营地-火
    32201: Condition.FRENZY,  # 癫火营地-癫火
    34001: Condition.BLEED,  # 鲜血遗迹-出血
    34002: Condition.FROST,  # 萨米尔遗迹-冻伤
    34003: Attribute.HOLY,  # 白金遗迹-圣
    34100: Condition.POISON,  # 调香师遗迹-中毒
    34101: Condition.POISON,  # 堕落调香师遗迹-中毒
    34102: Attribute.MAGIC,  # 法师遗迹-魔
    34103: Condition.FROST,  # 白金射手遗迹-冻伤
    34104: Condition.SLEEP,  # 卢恩熊遗迹-睡眠
    34200: Condition.DEATH,  # 蚯蚓脸遗迹-咒死
    34300: Attribute.THUNDER,  # 兽人遗迹-雷
    38000: Attribute.HOLY,  # 使者教堂-圣
    38100: Attribute.FIRE,  # 火焰教堂-火
    # dlc
    50001: Condition.POISON,  # 毒沼泽
    50011: Condition.POISON,  # 毒沼泽
    50020: Condition.FROST,  # 冻伤沼泽
    50030: Condition.SLEEP,  # 睡眠沼泽
    50040: Condition.CORRUPTION,  # 腐败沼泽
    50050: Condition.FRENZY,  # 癫火沼泽
    50060: Condition.BLEED,  # 出血沼泽
    50102: Condition.BLEED,  # 出血锻造村
    50103: Attribute.THUNDER,  # 雷锻造村
    50104: Attribute.HOLY,  # 圣锻造村
    50113: Attribute.FIRE,  # 火锻造村
    50114: Condition.POISON,  # 毒锻造村
    50116: Attribute.THUNDER,  # 雷锻造村
    53580: Attribute.FIRE,  # 火左上城
    53590: Attribute.MAGIC,  # 魔左上城
    53670: Condition.CORRUPTION,  # 腐败右下城
    53680: Attribute.HOLY,  # 圣右下城
    52500: Condition.BLEED,  # 血左废墟
    52520: Condition.POISON,  # 毒左废墟
    52570: Condition.SLEEP,  # 催眠右下废墟
    52550: Attribute.MAGIC,  # 魔右下废墟
    52450: Condition.SLEEP,  # 催眠右上教堂
    52460: Attribute.THUNDER,  # 雷右上教堂
    52400: Attribute.HOLY,  # 圣下教堂
    52420: Condition.FROST,  # 冻伤下教堂
}


def get_poi_key(ctype: int) -> int | None:
    """
    获取POI类型对应的基础图标类别
    """
    if ctype // 100 in POI_ICONS:
        return ctype // 100
    if ctype // 1000 in POI_ICONS:
        return ctype // 1000
    return None


def match_prefix(ctype: int, prefix: list[int] | int) -> bool:
    """
    判断建筑类型是否以指定前缀开头
    """
    if isinstance(prefix, int):
        prefix = [prefix]
    for p in prefix:
        if p == 0:
            if ctype == 0:
                return True
            continue
        x = ctype
        while x:
            if x < p:
                break
            if x == p:
                return True
            x //= 10
    return False


def has_same_base_icon(ctype1: int, ctype2: int) -> bool:
    """
    判断两个建筑类型是否使用相同的基础图标
    """
    if ctype1 // 10000 == 5 or ctype2 // 10000 == 5:
        return ctype1 // 100 == ctype2 // 100  # DLC建筑必须前三位完全相同才共用图标
    else:
        return ctype1 // 1000 == ctype2 // 1000


@dataclass
class SubPoiInfo:
    ctypes: set[int]  # 包含该子图标的POI类型
    image: Image.Image  # 带子图标的POI图像


@dataclass
class PoiCategoryInfo:
    base_image: Image.Image  # 不包含子图标的基础图像
    subtypes: dict[Attribute | Condition | None, SubPoiInfo]  # 子图标对应的图像和带子图标的POI类型
    resized_images: dict[tuple[int, int], Image.Image] = field(default_factory=dict)

    def get_resized_image(self, size: tuple[int, int]) -> Image.Image:
        if size not in self.resized_images:
            self.resized_images[size] = self.base_image.resize(size, resample=PIL_RESAMPLE_METHOD)
        return self.resized_images[size]


def get_poi_image(construct_type: int, with_subicon: bool = False) -> Image.Image:
    poi_key = construct_type // 100 if construct_type // 100 in POI_ICONS else construct_type // 1000
    offset_x, offset_y = POI_ICON_OFFSET.get(poi_key, (0, 0))
    x, y = STD_POI_SIZE[0] // 2, STD_POI_SIZE[1] // 2
    img = Image.new("RGBA", STD_POI_SIZE, (0, 0, 0, 0))
    if construct_type:
        icon, icon_scale = POI_ICONS[poi_key], POI_ICON_SCALE[poi_key]
        icon_size = (
            int(icon.size[0] * icon_scale * STD_MAP_SIZE[0] / 750),
            int(icon.size[1] * icon_scale * STD_MAP_SIZE[1] / 750),
        )
        icon = icon.resize(icon_size, resample=PIL_RESAMPLE_METHOD)
        icon_pos = (x - icon_size[0] // 2 + offset_x, y - icon_size[1] // 2 + offset_y)
        img.alpha_composite(icon, icon_pos)
        if with_subicon and construct_type in CTYPE_SUBICON_MAP:
            subicon = CTYPE_SUBICON_MAP[construct_type]
            subicon = SUBICON_IMAGES.get(subicon)
            subicon_size = (
                int(STD_MAP_SIZE[0] * 0.0195),
                int(STD_MAP_SIZE[1] * 0.0195),
            )
            subicon = subicon.resize(subicon_size, resample=PIL_RESAMPLE_METHOD)
            subicon_pos = (
                int(x - subicon_size[0] / 2 + STD_MAP_SIZE[0] * 0.013),
                int(y + subicon_size[1] / 2 + STD_MAP_SIZE[1] * -0.007),
            )
            img.alpha_composite(subicon, subicon_pos)
    return img


def load_default_map_info(language: str = "zh_CN") -> MapInfo:
    """Bundled map CSVs with display names in ``language``."""
    info = load_map_info(
        get_data_path("csv/map_patterns.csv"),
        get_data_path("csv/constructs.csv"),
        str(I18N_DIR / "zh_CN-names.csv"),
        get_data_path("csv/positions.csv"),
    )
    info.name_dict = load_names(language)
    return info


def build_poi_categories(info: MapInfo) -> tuple[dict[int, Image.Image], dict[int, PoiCategoryInfo]]:
    """POI icons per construct type and per base-icon category (``0`` is the empty category)."""
    all_poi_construct_types = set()
    for es in info.all_earth_shiftings:
        for nl in info.all_nightlords:
            all_poi_construct_types.update(info.all_poi_construct_type.get((es, nl), set()))

    all_poi_images: dict[int, Image.Image] = {}  # 所有POI类型对应图标
    poi_cate_info: dict[int, PoiCategoryInfo] = {}  # POI大类别对应图标信息
    for ctype in all_poi_construct_types:
        if poi_key := get_poi_key(ctype):
            if poi_key not in poi_cate_info:
                poi_cate_info[poi_key] = PoiCategoryInfo(
                    base_image=get_poi_image(ctype, with_subicon=False),
                    subtypes={},
                )
            cate = poi_cate_info[poi_key]
            subicon = CTYPE_SUBICON_MAP.get(ctype)
            if subicon not in cate.subtypes:
                cate.subtypes[subicon] = SubPoiInfo(
                    ctypes=set(),
                    image=get_poi_image(ctype, with_subicon=True),
                )
            cate.subtypes[subicon].ctypes.add(ctype)
            all_poi_images[ctype] = cate.subtypes[subicon].image
    # 无建筑
    all_poi_images[0] = Image.new("RGBA", STD_POI_SIZE, (0, 0, 0, 0))
    poi_cate_info[0] = PoiCategoryInfo(
        base_image=all_poi_images[0],
        subtypes={
            None: SubPoiInfo(
                ctypes={0},
                image=all_poi_images[0],
            )
        },
    )
    return all_poi_images, poi_cate_info


@dataclass
class MapPatternMatchResult:
    pattern: MapPattern
    nightlord: int | None
    score: int
    error: int


@dataclass
class MapDetectParam:
    map_region: tuple[int, int, int, int] | None = None
    img: np.ndarray | None = None
    earth_shifting: int | None = None
    do_match_full_map: bool = False
    do_match_earth_shifting: bool = False
    do_match_pattern: bool = False
    return_pattern_topk: int | None = None
    # Recognize only these POI positions; ``nightlord`` narrows their possible types.
    poi_positions: list[Position] | None = None
    nightlord: int | None = None
    # Draw known patterns in this order without matching; needs no image.
    draw_pattern_ids: list[int] | None = None


@dataclass
class MapDetectResult:
    img: np.ndarray | None = None
    is_full_map: bool | None = None
    earth_shifting: int | None = None
    earth_shifting_score: float | None = None
    patterns: list[MapPattern] | None = None
    overlay_images: list[Image.Image] | None = None
    poi_types: dict[Position, int] | None = None


class MapDetector:
    def __init__(self, config: MapDetectionSettings | None = None, *, language: str | None = None) -> None:
        self.config = config or MapDetectionSettings()
        localized = rendering_translator(language)
        self._tr = lambda key, **kwargs: localized.tr("map_detect", key, **kwargs)
        # 地图信息
        self.info = load_default_map_info(localized.language)

        self._poi_cnn: PoiCnn | None = None

        # 初始化POI信息
        self.all_poi_images, self.poi_cate_info = build_poi_categories(self.info)

        # 初始化夜王图标
        nightlords = [(None, UNKNOWN_NIGHTLORD_ICON)]
        for nl, icon in NIGHTLORD_ICONS.items():
            nightlords.append((nl, icon))
        for nl, icon in EVERNIGHT_NIGHTLORD_ICONS.items():
            nightlords.append((nl, icon))
        for i in range(len(nightlords)):
            nightlord, icon = nightlords[i]
            target_img = NIGHTLORD_ICON_BG.copy()
            cx, cy = target_img.size[0] // 2, target_img.size[1] // 2
            icon_scale = 0.8 if nightlord is not None else 0.9
            icon = icon.resize(
                (int(icon.size[0] * icon_scale), int(icon.size[1] * icon_scale)), resample=PIL_RESAMPLE_METHOD
            )
            iw, ih = icon.size
            target_img.alpha_composite(icon, (cx - iw // 2, cy - ih // 2))
            target_img = target_img.resize(
                (int(MATCH_NIGHTLORD_SIZE[0] * 0.2), int(MATCH_NIGHTLORD_SIZE[1] * 0.2)),
                resample=PIL_RESAMPLE_METHOD,
            )
            h, w = target_img.size
            target_img = target_img.crop((int(w * 0.3), int(h * 0.3), int(w * 0.7), int(h * 0.7)))
            nightlords[i] = (nightlord, np.array(target_img)[..., :3])
        self.nightlord_icons: list[tuple[int | None, np.ndarray]] = nightlords

    def _match_full_map(self, img: np.ndarray) -> float:
        """Find the lower-left circular HUD at its calibrated position and scale.

        Normalize local contrast before Hough voting so dark/low-contrast maps
        retain their edges. Before normalization, reject insufficient contrast
        and obvious raised/tinted shadow floors from a solid-color backdrop.
        These checks cannot distinguish every fade from brightness adjustment.
        """
        config = self.config
        if img.ndim != 3 or img.shape[2] != 3 or min(img.shape[:2]) < 5:
            return float("inf")
        thumbnail = cv2.resize(img, (160, 160), interpolation=cv2.INTER_AREA)
        shadows = np.percentile(thumbnail.reshape(-1, 3), 1, axis=0)
        # Broad limits on shadow level and channel imbalance, not a palette match.
        # Keep these in the original intensity range: normalization would erase
        # the evidence of a bright or strongly colored compositing background.
        if shadows.min() > 96 or np.ptp(shadows) > 56:
            return float("inf")
        img = img[-int(img.shape[0] * 0.22) :, : int(img.shape[1] * 0.22)]
        img = cv2.resize(img, CHECK_FULL_MAP_STD_SIZE, interpolation=cv2.INTER_LINEAR)
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        if np.ptp(gray) < 48:
            return float("inf")
        gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
        error = float("inf")
        for smooth in (False, True):
            # A light fallback suppresses sharpening halos without weakening
            # the position, radius, or original-contrast requirements.
            edges = cv2.GaussianBlur(gray, (3, 3), 0.4) if smooth else gray
            for thres in config.full_map_hough_circle_thres:
                res = cv2.HoughCircles(
                    edges,
                    cv2.HOUGH_GRADIENT,
                    dp=1,
                    minDist=20,
                    param1=thres,
                    param2=30,
                    minRadius=int(img.shape[0] * 0.4),
                    maxRadius=int(img.shape[0] * 0.5),
                )
                if res is not None:
                    for cx, cy, radius in res[0]:
                        if abs(cx - img.shape[1] * 0.5) <= 8 and abs(cy - img.shape[0] * 0.5) <= 8:
                            error = min(error, float((radius - img.shape[0] * 0.425) ** 2))
                if error <= config.full_map_error_threshold:
                    break
            if error <= config.full_map_error_threshold:
                break
        log.debug(f"MapDetector: Full map match error: {error:.4f}")
        return error

    def _match_earth_shifting(self, img: np.ndarray) -> tuple[int | None, float]:
        """Dispatch terrain recognition, returning the selected algorithm's native score."""
        if self.config.earth_shifting_algorithm == "template":
            return self._match_earth_shifting_template(img)
        return self._match_earth_shifting_ncc(img)

    def _match_earth_shifting_ncc(self, img: np.ndarray) -> tuple[int | None, float]:
        """Compare equalized grayscale centers, following the TGH notebook's NCC matcher.

        Return the raw correlation in [-1, 1], with higher scores indicating a match.
        Constant images have no structure and cannot identify a terrain.
        """
        t = time.time()
        margin = MATCH_EARTH_SHIFTING_SIZE[0] // 8

        def preprocess(image: np.ndarray) -> np.ndarray:
            image = cv2.resize(image, MATCH_EARTH_SHIFTING_SIZE, interpolation=CV2_RESIZE_METHOD)
            gray = cv2.equalizeHist(cv2.cvtColor(image, cv2.COLOR_RGB2GRAY))
            center = gray[margin:-margin, margin:-margin].astype(np.float32).ravel()
            return center - center.mean()

        center = preprocess(img)
        if np.dot(center, center) < 1e-7:
            return None, 0.0
        best_map_id, best_correlation = None, -float("inf")
        for map_id, map_img in MAP_BGS.items():
            template = preprocess(map_img)
            denominator = np.sqrt(np.dot(center, center) * np.dot(template, template))
            correlation = 0.0 if denominator < 1e-7 else float(np.dot(center, template) / denominator)
            correlation = float(np.clip(correlation, -1.0, 1.0))
            if correlation > best_correlation:
                best_map_id, best_correlation = map_id, correlation
        log.info(
            "MapDetector: Match earth shifting (NCC): best map %s correlation %.4f, time cost: %.4fs",
            best_map_id,
            best_correlation,
            time.time() - t,
        )
        return best_map_id, best_correlation

    def _match_earth_shifting_template(self, img: np.ndarray) -> tuple[int | None, float]:
        """Legacy color template matcher, retaining its original error scale."""
        t = time.time()
        img = cv2.resize(img, MATCH_EARTH_SHIFTING_SIZE, interpolation=CV2_RESIZE_METHOD)
        x, y, w, h = MATCH_EARTH_SHIFTING_REGION
        img = img[y : y + h, x : x + w].astype(int)
        best_map_id, best_score = None, float("inf")
        offset, stride = MATCH_EARTH_SHIFTING_OFFSET_AND_STRIDE
        min_scale, max_scale, scale_num = MATCH_EARTH_SHIFTING_SCALES
        for map_id, map_img in MAP_BGS.items():
            score = float("inf")
            for scale in np.linspace(min_scale, max_scale, scale_num, endpoint=True):
                size = (int(MATCH_EARTH_SHIFTING_SIZE[0] * scale), int(MATCH_EARTH_SHIFTING_SIZE[1] * scale))
                map_resized = cv2.resize(map_img, size, interpolation=CV2_RESIZE_METHOD).astype(int)
                for dx in range(-offset, offset + 1, stride):
                    for dy in range(-offset, offset + 1, stride):
                        map_shifted = map_resized[y + dy : y + h + dy, x + dx : x + w + dx]
                        diff = np.abs(img - map_shifted)
                        diff[diff > 100] = 0
                        diff = np.linalg.norm(diff, axis=2)
                        cur_score = np.median(diff)
                        score = min(score, cur_score)
            if score < best_score:
                best_score = score
                best_map_id = map_id
        log.info(
            f"MapDetector: Match earth shifting: best map {best_map_id} score {best_score:.4f}, "
            f"time cost: {time.time() - t:.4f}s"
        )
        return best_map_id, best_score

    def _match_nightlord(self, img: np.ndarray) -> tuple[int | None, float]:
        t = time.time()
        img = cv2.resize(img, MATCH_NIGHTLORD_SIZE, interpolation=CV2_RESIZE_METHOD)
        h, w = img.shape[0], img.shape[1]
        img = img[-int(h * 0.15) : -int(h * 0.05), int(w * 0.06) : int(w * 0.16)]

        best_nightlord, best_score = None, float("inf")

        for nightlord, icon in self.nightlord_icons:
            _match_result, score = match_template(img, icon, MATCH_NIGHTLORD_SCALES)
            if score < best_score:
                best_score = score
                best_nightlord = nightlord

        log.info(
            f"MapDetector: Match nightlord: best nightlord {best_nightlord} score {best_score:.4f}, "
            f"time cost: {time.time() - t:.4f}s"
        )
        return best_nightlord, best_score

    def _get_poi_image(self, construct_type: int, with_subicon: bool = False) -> Image.Image:
        return get_poi_image(construct_type, with_subicon)

    def _match_pois(
        self,
        map_img: np.ndarray,
        map_bg: np.ndarray,
        positions: list[Position],
        earth_shifting: int,
        nightlord: int | None = None,
    ) -> dict[Position, tuple[int, float]]:
        """Recognize a full batch or a manual selection using the configured backend."""
        if self.config.poi_algorithm == "template":
            return {
                pos: self._match_poi(map_img, map_bg, pos, earth_shifting, nightlord) for pos in positions
            }
        if not positions:
            return {}
        if self._poi_cnn is None:
            self._poi_cnn = PoiCnn()
        base, corner = self._poi_cnn.predict(map_img, positions)
        nightlords = [nightlord] if nightlord is not None else self.info.all_nightlords
        results = {}
        for i, pos in enumerate(positions):
            possible = set()
            for nl in nightlords:
                possible.update(self.info.possible_poi_types.get((earth_shifting, nl, pos), set()))
            results[pos] = self._select_cnn_poi(base[i], corner[i], possible)
        return results

    def _select_cnn_poi(self, base: np.ndarray, corner: np.ndarray, possible: set[int]) -> tuple[int, float]:
        """Constrain base first, then constrain corners to that base at this position."""
        by_key: dict[int, list[int]] = {}
        for ctype in sorted(possible):
            key = get_poi_key(ctype) or 0
            if key in BASE_CLASSES:
                by_key.setdefault(key, []).append(ctype)
        if not by_key:
            return 0, 0.0
        key = max(by_key, key=lambda k: float(base[list(BASE_CLASSES[k])].sum()))
        candidates = by_key[key]

        def corner_index(ctype: int) -> int:
            subicon = CTYPE_SUBICON_MAP.get(ctype)
            if isinstance(subicon, Condition):
                return subicon.value + 1
            if isinstance(subicon, Attribute):
                return subicon.value + 8
            return 0

        best = max(candidates, key=lambda c: float(corner[corner_index(c)]))
        confidence = float(base[list(BASE_CLASSES[key])].sum() * corner[corner_index(best)])
        return best, confidence

    def _match_poi(
        self,
        map_img: np.ndarray,
        map_bg: np.ndarray,
        pos: Position,
        earth_shifting: int,
        nightlord: int | None = None,
    ) -> tuple[int, float]:
        if self.config.poi_algorithm == "cnn":
            return self._match_pois(map_img, map_bg, [pos], earth_shifting, nightlord)[pos]
        img = map_img[
            pos[1] - STD_POI_SIZE[1] // 2 : pos[1] - STD_POI_SIZE[1] // 2 + STD_POI_SIZE[1],
            pos[0] - STD_POI_SIZE[0] // 2 : pos[0] - STD_POI_SIZE[1] // 2 + STD_POI_SIZE[0],
        ]
        bg = map_bg[
            pos[1] - STD_POI_SIZE[1] // 2 : pos[1] - STD_POI_SIZE[1] // 2 + STD_POI_SIZE[1],
            pos[0] - STD_POI_SIZE[0] // 2 : pos[0] - STD_POI_SIZE[1] // 2 + STD_POI_SIZE[0],
        ]

        # 判断建筑类型
        downsample_size = (16, 16)
        max_offset = 4
        offset_stride = 2
        scale_range = (0.9, 1.1, 5)

        img_for_poi = cv2.resize(img, downsample_size, interpolation=CV2_RESIZE_METHOD)
        h, w, _ = img_for_poi.shape
        h_min, h_max, w_min, w_max = int(h * 0.2), int(h * 0.8), int(w * 0.2), int(w * 0.6)
        img_for_poi = img_for_poi[h_min:h_max, w_min:w_max]
        bg = Image.fromarray(bg).convert("RGBA")

        best_poi_key = None
        best_poi_key_score = float("inf")

        # 收集该位置可能出现的POI类型
        nightlords = [nightlord] if nightlord is not None else self.info.all_nightlords
        possible_ctypes = set()
        for nl in nightlords:
            possible_ctypes.update(self.info.possible_poi_types.get((earth_shifting, nl, pos), set()))

        for poi_key, info in self.poi_cate_info.items():
            if not any(match_prefix(ctype, poi_key) for ctype in possible_ctypes):
                continue  # 仅匹配该位置可能出现的POI类型

            target_imgs = []
            for dx in range(-max_offset, max_offset + 1, offset_stride):
                for dy in range(-max_offset, max_offset + 1, offset_stride):
                    for s in np.linspace(scale_range[0], scale_range[1], scale_range[2], endpoint=True):
                        size = (int(STD_POI_SIZE[0] * s), int(STD_POI_SIZE[1] * s))
                        resized_poi_icon = info.get_resized_image(size)
                        poi_img = bg.copy()
                        poi_img.alpha_composite(resized_poi_icon, (dx, dy))
                        poi_img = np.array(poi_img)[..., :3]
                        poi_img = cv2.resize(poi_img, downsample_size, interpolation=CV2_RESIZE_METHOD)
                        poi_img = poi_img[h_min:h_max, w_min:w_max]
                        target_imgs.append(poi_img)

            target_imgs = np.array(target_imgs).astype(np.float32)
            diffs = np.mean((target_imgs - img_for_poi.astype(np.float32)) ** 2, axis=(1, 2, 3))
            min_idx = np.argmin(diffs)
            poi_key_score = diffs[min_idx]
            if poi_key_score < best_poi_key_score:
                best_poi_key_score = poi_key_score
                best_poi_key = poi_key

        # 判断子图标类型
        downsample_size = (64, 64)
        scale_range = (0.9, 1.1, 5)

        img_for_subicon = cv2.resize(img, downsample_size, interpolation=CV2_RESIZE_METHOD)
        h, w, _ = img_for_subicon.shape
        img_for_subicon = img_for_subicon[int(h * 0.4) :, int(w * 0.4) :]
        img_for_subicon = cv2.GaussianBlur(img_for_subicon, (3, 3), 0)

        best_subicon = None
        best_subicon_score = float("inf")

        for subicon, _info in self.poi_cate_info[best_poi_key].subtypes.items():
            if not subicon:
                continue
            subicon_img = SUBICON_IMAGES[subicon]
            for s in np.linspace(scale_range[0], scale_range[1], scale_range[2], endpoint=True):
                size = (int(downsample_size[0] * s * 0.3), int(downsample_size[1] * s * 0.3))
                target_img = subicon_img.resize(size, resample=Image.Resampling.NEAREST).convert("RGB")
                target_img = np.array(target_img).astype(np.uint8)
                target_img = cv2.GaussianBlur(target_img, (3, 3), 0)
                th, tw = target_img.shape[0], target_img.shape[1]
                target_img = target_img[int(th * 0.1) : int(th * 0.9), int(tw * 0.1) : int(tw * 0.9)]
                _match_result, match_val = match_template(img_for_subicon, target_img, scales=(1.0, 1.0, 1))
                if match_val < best_subicon_score:
                    best_subicon_score = match_val
                    best_subicon = subicon

                # if abs(1.0 - s) < 1e-3:
                #     vis[:size[0], :size[1], :] = target_img

        if (
            None in self.poi_cate_info[best_poi_key].subtypes
            and best_subicon_score > self.config.subicon_template_match_threshold
        ):
            best_subicon = None

        best_ctype = sorted(list(self.poi_cate_info[best_poi_key].subtypes.get(best_subicon).ctypes))[0]
        return best_ctype, best_poi_key_score * best_subicon_score

    def _prepare_poi_image(self, img: np.ndarray, earth_shifting: int) -> tuple[np.ndarray, np.ndarray]:
        """Standard-size map aligned to its POI-matching background, and that background."""
        if img.shape[:2] != (STD_MAP_SIZE[1], STD_MAP_SIZE[0]):
            img = cv2.resize(img, STD_MAP_SIZE, interpolation=CV2_RESIZE_METHOD)
        map_bg = open_cv2_image(f"maps_poi_match/{MAG_BG_FOR_POI_MATCH_INDEX_MAP[earth_shifting]}.jpg")
        map_bg = cv2.resize(map_bg, STD_MAP_SIZE, interpolation=CV2_RESIZE_METHOD)
        try:
            align_t = time.time()
            align_region = (
                int(STD_MAP_SIZE[0] * 0.2),
                int(STD_MAP_SIZE[1] * 0.2),
                int(STD_MAP_SIZE[0] * 0.6),
                int(STD_MAP_SIZE[1] * 0.6),
            )
            img = align_image(img, map_bg, align_region)
            log.info(f"MapDetector: Align map image time cost: {time.time() - align_t:.4f}s")
        except Exception as e:
            log.warning(f"MapDetector: Align map image failed: {e}")
        return img, map_bg

    def _match_map_pattern(
        self, img: np.ndarray, earth_shifting: int, topk: int
    ) -> list[MapPatternMatchResult]:
        assert earth_shifting is not None, "earth_shifing should be provided when matching map pattern"

        t = time.time()
        img = cv2.resize(img, STD_MAP_SIZE, interpolation=CV2_RESIZE_METHOD)

        # 识别夜王
        nightlord, _ = self._match_nightlord(img)

        # 校准偏移
        img, map_bg = self._prepare_poi_image(img, earth_shifting)

        # 识别POI
        poi_result: dict[Position, int] = {}
        poi_result_img = img.copy()  # for debug

        all_poi_pos = set()  # 收集所有待匹配POI点
        nightlords = [nightlord] if nightlord is not None else self.info.all_nightlords
        for nl in nightlords:
            all_poi_pos.update(self.info.all_poi_pos.get((earth_shifting, nl), set()))

        ratio = (
            self.config.poi_match_sample_ratio_w_nightlord
            if nightlord is not None
            else self.config.poi_match_sample_ratio_wo_nightlord
        )
        sample_num = max(8, int(len(all_poi_pos) * ratio))  # 最少采样8个POI点
        all_poi_pos = list(all_poi_pos)
        random.shuffle(all_poi_pos)

        positions = sorted(all_poi_pos[:sample_num])
        matches = self._match_pois(img, map_bg, positions, earth_shifting, nightlord)
        for x, y in positions:
            ctype, score = matches[(x, y)]
            poi_result[(x, y)] = ctype

            # 绘制调试图
            paste_cv2(
                poi_result_img,
                np.array(self.all_poi_images[ctype])[..., :3],
                (x - STD_POI_SIZE[0] // 2, y - STD_POI_SIZE[1] // 2),
            )
            cv2.circle(poi_result_img, (x, y), 2, (255, 0, 0), 3)

        # 保存结果用于调试
        cv2.imwrite(get_appdata_path("map.jpg"), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
        cv2.imwrite(get_appdata_path("map_poi_result.jpg"), cv2.cvtColor(poi_result_img, cv2.COLOR_RGB2BGR))

        # 匹配地图模式
        empty_construction = Construct(type=0, pos=0, is_display=False)
        results: list[MapPatternMatchResult] = []
        for pattern in self.info.patterns:
            if pattern.earth_shifting != earth_shifting:
                continue
            if nightlord is not None and pattern.nightlord != nightlord:
                continue
            score, error = 0, 0
            for pos, ctype in poi_result.items():
                expect_ctype = pattern.pos_constructions.get(pos, empty_construction).type
                if expect_ctype not in self.all_poi_images:
                    expect_ctype = 0

                subicon = CTYPE_SUBICON_MAP.get(ctype)
                expect_subicon = CTYPE_SUBICON_MAP.get(expect_ctype)

                if not has_same_base_icon(ctype, expect_ctype):  # 建筑类型不符合
                    if subicon == expect_subicon:
                        score += 1  # 子图标符合
                        error += 3
                    else:
                        score += 0
                        error += 10
                else:
                    if subicon == expect_subicon:
                        score += 10  # 完全符合
                        error += 0
                    elif subicon or expect_subicon:
                        score += 0  # 一个有子图标一个没有
                        error += 10
                    else:
                        score += 3  # 子图标不符合
                        error += 1

            # log.info(f"pattern {pattern.id} match score: {score} error: {error}")
            results.append(
                MapPatternMatchResult(
                    pattern=pattern,
                    nightlord=nightlord,
                    score=score,
                    error=error,
                )
            )

        # 使用Error最小的结果
        results = sorted(results, key=lambda x: (x.error, -x.score))
        best_patterns_by_error = results[:topk]
        log.info(
            f"Match map pattern: return {[p.pattern.id for p in best_patterns_by_error]}, "
            f"time cost: {time.time() - t:.4f}s"
        )
        return best_patterns_by_error

    def _draw_overlay_image(
        self, match_result: MapPatternMatchResult, draw_size: tuple[int, int], result_index: int
    ) -> Image.Image:
        pattern = match_result.pattern

        def scale_size(p: int | float | Position) -> int | Position:
            # 以750x750为标准尺寸
            if isinstance(p, (int, float)):
                return int(p * draw_size[0] / 750)
            return (int(p[0] * draw_size[0] / 750), int(p[1] * draw_size[1] / 750))

        def open_with_draw_size(path: str, size: tuple[int, int]) -> Image.Image:
            return open_pil_image(path, scale_size(size))

        def get_name(ctype: int) -> str:
            return self.info.get_name(ctype) or str(ctype)

        def get_event_text(pattern: MapPattern) -> str | None:
            flag, value = pattern.event_flag, pattern.event_value
            if flag == 0:
                return None
            flag_name = get_name(flag)
            value_name = get_name(value)
            if flag in [7705, 7725]:
                return f"{flag_name} {value_name}"
            else:
                return f"{flag_name}"

        t = time.time()
        # 图片资源和常量
        boss1_icon = open_with_draw_size("icons/boss1.png", (24, 24))
        boss2_icon = open_with_draw_size("icons/boss2.png", (24, 24))
        carriage_icon = open_with_draw_size("icons/carriage.png", (32, 32))
        boss1_ctypes = [
            46510,
            46570,
            46590,
            46620,
            46650,
            46690,
            46710,
            46720,
            46770,
            46810,
            46820,
            46860,
            46880,
            46910,
            46950,
            45510,
            46550,
        ]
        boss2_ctypes = [
            46520,
            46530,
            46540,
            46560,
            46630,
            46640,
            46660,
            46670,
            46680,
            46740,
            46870,
            46580,
        ]

        night_circle_icon = open_with_draw_size("icons/night_circle.png", (112, 112))

        main_castle_upperfloor_pos = scale_size((328, 409))
        main_castle_basement_pos = scale_size((355, 409))

        rotrew_icon = open_with_draw_size("icons/rot_rew.png", (37, 37))
        rotrew_pos = {
            1046300590: scale_size((477, 583)),
            1057300590: scale_size((600, 452)),
            1047300590: scale_size((423, 500)),
        }

        font_size_large = scale_size(16)
        font_size_small = scale_size(14)
        outline_color = (0, 0, 0, 255)
        outline_w_large = max(1, scale_size(2))
        outline_w_small = max(1, scale_size(2))

        event_icon = open_with_draw_size("icons/event.png", (45, 45))

        # 大空洞神授塔BOSS对应位置索引
        tgh_floor_boss_pos_index = {
            1111: ("RB", 1),
            1112: ("RB", 2),
            1113: ("RB", 3),
            1114: ("LT", 1),
            1115: ("LT", 2),
            1116: ("LT", 3),
        }

        # 开始绘制
        img = Image.new("RGBA", draw_size, (0, 0, 0, 0))
        texts, icons = [], []

        # day1 boss
        x, y = scale_size(pattern.day1_pos)
        name = get_name(pattern.day1_boss) or self._tr("drawing.unknown_boss")
        extra_name = get_name(pattern.day1_extra_boss) if pattern.day1_extra_boss != -1 else None
        icons.append(((x, y), night_circle_icon))
        texts.append(
            (
                (x, y + scale_size(40)),
                self._tr("drawing.day_boss", day=1, name=name),
                font_size_large,
                (210, 210, 255, 255),
                outline_w_large,
                outline_color,
            )
        )
        if extra_name:
            texts.append(
                (
                    (x, y + scale_size(60)),
                    self._tr("drawing.extra_boss", name=extra_name),
                    font_size_large,
                    (255, 255, 255, 255),
                    outline_w_large,
                    outline_color,
                )
            )

        # day2 boss
        x, y = scale_size(pattern.day2_pos)
        name = get_name(pattern.day2_boss) or self._tr("drawing.unknown_boss")
        extra_name = get_name(pattern.day2_extra_boss) if pattern.day2_extra_boss != -1 else None
        icons.append(((x, y), night_circle_icon))
        texts.append(
            (
                (x, y + scale_size(40)),
                self._tr("drawing.day_boss", day=2, name=name),
                font_size_large,
                (210, 210, 255, 255),
                outline_w_large,
                outline_color,
            )
        )
        if extra_name:
            texts.append(
                (
                    (x, y + scale_size(60)),
                    self._tr("drawing.extra_boss", name=extra_name),
                    font_size_large,
                    (255, 255, 255, 255),
                    outline_w_large,
                    outline_color,
                )
            )

        # 大空洞第二天缩圈位置
        day2_lefttop = pattern.day2_pos_idx == 12000
        in_circle_color = (200, 255, 200, 255)
        out_circle_color = (255, 200, 200, 255)

        for pos, construct in pattern.pos_constructions.items():
            pos = scale_size(pos)
            x, y = pos
            ctype = construct.type

            def match(*prefixes) -> bool:
                s = str(ctype)  # noqa: B023 -- called immediately in this loop iteration
                return any(s.startswith(str(prefix)) for prefix in prefixes)

            def process_underground_name(name: str):
                if construct.is_underground:  # noqa: B023 -- immediate loop-local helper
                    return "↓" + name
                return name

            # boss
            if (
                match(45, 46)
                and not match(460)
                and (ctype == 45510 or ctype // 1000 != 45)
                and ctype not in (46780,)
            ):
                name = get_name(ctype)
                if pos == main_castle_upperfloor_pos:
                    y -= scale_size(10)
                    x += scale_size(13)
                    name = self._tr("drawing.rooftop", name=name)
                elif pos == main_castle_basement_pos:
                    y += scale_size(10)
                    x -= scale_size(13)
                    name = self._tr("drawing.basement", name=name)
                else:
                    y += scale_size(15)
                    if ctype in boss1_ctypes:
                        icons.append(((x, y - scale_size(20)), boss1_icon))
                    elif ctype in boss2_ctypes:
                        icons.append(((x, y - scale_size(20)), boss2_icon))
                color = (255, 255, 255, 255) if not construct.is_underground else (200, 200, 255, 255)
                if name:
                    texts.append(
                        (
                            (x, y),
                            process_underground_name(name),
                            font_size_large,
                            color,
                            outline_w_large,
                            outline_color,
                        )
                    )

            # 主城类型
            if match(494) and ctype != 49400:
                y -= scale_size(30)
                x -= scale_size(15)
                texts.append(
                    (
                        (x, y),
                        get_name(ctype),
                        font_size_large,
                        (255, 255, 0, 255),
                        outline_w_large,
                        outline_color,
                    )
                )
            # 主城类型（大空洞）
            if match(5358, 5359, 5367, 5368):
                y += scale_size(25)
                x += scale_size(5)
                color = in_circle_color if match(536) ^ day2_lefttop else out_circle_color
                texts.append(
                    ((x, y), get_name(ctype), font_size_large, color, outline_w_large, outline_color)
                )
                # 下水道类型
                for _p2, c2 in pattern.pos_constructions.items():
                    if (match(536) and c2.type in (53700, 53710, 53720)) or (
                        match(535) and c2.type in (53600, 53610)
                    ):
                        y += scale_size(20)
                        texts.append(
                            (
                                (x, y),
                                "↓" + get_name(c2.type),
                                font_size_large,
                                color,
                                outline_w_large,
                                outline_color,
                            )
                        )
            # 法师塔
            if match(400, 5110):
                texts.append(
                    (
                        (x, y),
                        get_name(ctype),
                        font_size_small,
                        (210, 255, 200, 255),
                        outline_w_small,
                        outline_color,
                    )
                )
            # 马车
            if match(4500, 4501, 51150):
                icons.append(((x, y), carriage_icon))
            # POI
            if match(
                30,
                32,
                34,
                38,
                500,
                501,
                524,
                525,
            ):
                color = (200, 220, 150, 255) if not construct.is_underground else (250, 200, 250, 255)
                y += scale_size(15)
                texts.append(
                    (
                        (x, y),
                        process_underground_name(get_name(ctype)),
                        font_size_small,
                        color,
                        outline_w_small,
                        outline_color,
                    )
                )
            # 特殊事件（癫火塔除外）
            if 200 <= ctype // 100 <= 215:
                icons.append(((x, y), event_icon))
                y += scale_size(15)
                texts.append(
                    (
                        (x, y),
                        get_event_text(pattern),
                        font_size_small,
                        (255, 200, 200, 255),
                        outline_w_small,
                        outline_color,
                    )
                )
            # 血瓶
            if match(510, 41):
                y += scale_size(15)
                texts.append(
                    (
                        (x, y),
                        process_underground_name(self._tr("drawing.flask")),
                        font_size_small,
                        (255, 255, 0, 255),
                        outline_w_small,
                        outline_color,
                    )
                )
            # 神授塔BOSS
            if construct.pos_index in tgh_floor_boss_pos_index:
                floor_pos, floor_num = tgh_floor_boss_pos_index[construct.pos_index]
                x, y = scale_size((100, 280) if floor_pos == "LT" else (680, 530))
                y += scale_size((3 - floor_num) * 20)
                color = in_circle_color if (day2_lefttop ^ (floor_pos == "RB")) else out_circle_color
                texts.append(
                    (
                        (x, y),
                        self._tr("drawing.floor_boss", floor=floor_num, name=get_name(ctype)),
                        font_size_large,
                        color,
                        outline_w_large,
                        outline_color,
                    )
                )

        # 宝藏
        treasure_id = pattern.treasure * 10 + pattern.earth_shifting
        try:
            treasure = open_with_draw_size(f"treasures/treasure_{treasure_id}.png", (800, 800))
            icons.append((scale_size((375, 375)), treasure))
        except FileNotFoundError:
            log.warning(f"Treasure image not found: treasure_{treasure_id}.png")

        # 癫火塔
        if pattern.event_value == 3080:
            frenzy = open_with_draw_size(f"frenzy/Frenzy_{pattern.evpat_flag}.png", (800, 800))
            icons.append((scale_size((375, 375)), frenzy))

        # 腐败庇佑
        if pos := rotrew_pos.get(pattern.rot_rew):
            icons.append((pos, rotrew_icon))
            texts.append(
                (
                    (pos[0], pos[1] + scale_size(20)),
                    self._tr("drawing.blessing"),
                    font_size_small,
                    (255, 200, 200, 255),
                    outline_w_small,
                    outline_color,
                )
            )

        # 说明文本
        info_text_y_offset = 0
        text = f"#{pattern.id}"
        if match_result.error is not None:
            text += f" (#{result_index + 1} E:{match_result.error})"
        text += f"  {get_name(pattern.earth_shifting + 200000)} - {get_name(pattern.nightlord + 100000)}"
        if match_result.nightlord is None:
            text += self._tr("drawing.hidden_nightlord")
        texts.append(
            (
                scale_size((20, 10)),
                text,
                scale_size(22),
                (255, 255, 255, 255),
                scale_size(3),
                outline_color,
                "lt",
            )
        )
        info_text_y_offset += 28

        # 大空洞第二天缩圈位置
        if pattern.earth_shifting == 4:
            text = self._tr("drawing.upper_left" if day2_lefttop else "drawing.lower_right")
            text = self._tr("drawing.day2_circle", position=text)
            texts.append(
                (
                    scale_size((20, 10 + info_text_y_offset)),
                    text,
                    scale_size(22),
                    (255, 255, 255, 255),
                    scale_size(3),
                    outline_color,
                    "lt",
                )
            )
            info_text_y_offset += 28

        # 特殊事件
        if event_text := get_event_text(pattern):
            texts.append(
                (
                    scale_size((20, 10 + info_text_y_offset)),
                    self._tr("drawing.event", name=event_text),
                    scale_size(22),
                    (255, 255, 255, 255),
                    scale_size(3),
                    outline_color,
                    "lt",
                )
            )
            info_text_y_offset += 28

        for icon in icons:
            draw_icon(img, *icon)
        for text in texts:
            draw_text(img, *text)

        log.info(f"Draw overlay image size: {draw_size} time cost: {time.time() - t:.4f}s")

        # 保存结果用于调试
        img.convert("RGB").save(get_appdata_path(f"map_overlay_result_{result_index}.jpg"))

        return img

    def _overlay_draw_size(self, param: MapDetectParam) -> tuple[int, int]:
        config = self.config
        if config.fixed_map_overlay_draw_size is not None:
            return tuple(config.fixed_map_overlay_draw_size)
        if config.map_overlay_draw_size_ratio is not None:
            return (
                int(param.map_region[2] * config.map_overlay_draw_size_ratio),
                int(param.map_region[3] * config.map_overlay_draw_size_ratio),
            )
        return STD_MAP_SIZE

    def detect(self, param: MapDetectParam | None) -> MapDetectResult:
        config = self.config
        ret = MapDetectResult()
        if param is None or param.map_region is None:
            return ret

        # 绘制已知地图模式
        if param.draw_pattern_ids is not None:
            patterns_by_id = {p.id: p for p in self.info.patterns}
            draw_size = self._overlay_draw_size(param)
            ret.patterns = []
            ret.overlay_images = []
            for pattern_id in param.draw_pattern_ids:
                pattern = patterns_by_id.get(pattern_id)
                if pattern is None:
                    log.error(f"MapDetector: Unknown map pattern {pattern_id}")
                    continue
                result = MapPatternMatchResult(pattern=pattern, nightlord=param.nightlord, score=0, error=0)
                ret.overlay_images.append(self._draw_overlay_image(result, draw_size, len(ret.patterns)))
                ret.patterns.append(pattern)

        if param.img is None:
            return ret
        img = param.img
        ret.img = img

        # 判断是否是全图
        if param.do_match_full_map:
            full_map_error = self._match_full_map(img)
            ret.is_full_map = full_map_error <= config.full_map_error_threshold

        # 判断特殊地形
        if param.do_match_earth_shifting:
            earth_shifting, earth_shifting_score = self._match_earth_shifting(img)
            if config.earth_shifting_algorithm == "ncc":
                if earth_shifting_score < config.earth_shifting_ncc_threshold:
                    earth_shifting = None
            elif earth_shifting_score > config.earth_shifting_error_threshold:
                earth_shifting = None
            ret.earth_shifting = earth_shifting
            ret.earth_shifting_score = earth_shifting_score

        # 地图模式匹配
        if param.do_match_pattern:
            results = self._match_map_pattern(img, param.earth_shifting, topk=param.return_pattern_topk)

            # 决定信息绘制大小
            draw_size = self._overlay_draw_size(param)

            ret.patterns = []
            ret.overlay_images = []
            for i, result in enumerate(results):
                try:
                    log.info(f"MapDetector: Start to draw overlay image for pattern {result.pattern.id}")
                    overlay_img = self._draw_overlay_image(result, draw_size, i)
                    ret.overlay_images.append(overlay_img)
                    ret.patterns.append(result.pattern)
                    gc.collect()
                except Exception as e:
                    log.error(f"MapDetector: Draw overlay image of pattern {result.pattern.id} failed: {e}")

        # 识别指定位置的POI
        if param.poi_positions:
            assert param.earth_shifting is not None, "earth_shifting should be provided when matching POIs"
            aligned, map_bg = self._prepare_poi_image(img, param.earth_shifting)
            matches = self._match_pois(
                aligned, map_bg, param.poi_positions, param.earth_shifting, param.nightlord
            )
            ret.poi_types = {pos: ctype for pos, (ctype, _) in matches.items()}

        return ret
