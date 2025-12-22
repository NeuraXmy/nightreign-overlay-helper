import cv2
import os
import numpy as np
from dataclasses import dataclass, field
from PIL import Image
import time
from mss.base import MSSBase
from enum import Enum
import random

from src.config import Config
from src.logger import info, warning, error, debug
from src.common import get_appdata_path, get_data_path
from src.detector.map_info import (
    load_map_info, 
    STD_MAP_SIZE, 
    Position,
    MapPattern,
    Construct,
)
from src.detector.utils import (
    paste_cv2,
    draw_icon,
    draw_text,
    grab_region,
    match_template,
    align_image,
)


CV2_RESIZE_METHOD = cv2.INTER_CUBIC
PIL_RESAMPLE_METHOD = Image.Resampling.BICUBIC

def open_pil_image(path: str, size: tuple[int, int] | None = None) -> Image.Image:
    path = get_data_path(path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Image file not found: {path}")
    image = Image.open(path).convert("RGBA")
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
MAP_BGS = { i : open_cv2_image(f"maps/{i}.jpg") for i in range(6) }

MATCH_NIGHTLORD_SIZE = (300, 300)
NIGHTLORD_ICONS = { i : open_pil_image(f"icons/nightlord/{i}.png") for i in range(10) }
EVERNIGHT_NIGHTLORD_ICONS = { i : open_pil_image(f"icons/nightlord/e{i}.png") for i in range(9) }
UNKNOWN_NIGHTLORD_ICON = open_pil_image("icons/nightlord/unk.png")
NIGHTLORD_ICON_BG = open_pil_image("icons/nightlord/bg.png")
MATCH_NIGHTLORD_SCALES = (0.9, 1.1, 7)

POI_ICON_SCALE = { 
    30: 0.35, 32: 0.5, 34: 0.4, 37: 0.4, 38: 0.3, 40: 0.4, 41: 0.38, 
    510: 0.38, 511: 0.4, 500: 0.15, 501: 0.2, 524: 0.3, 525: 0.4, 
    535: 0.15, 536: 0.18,
}
POI_ICON_OFFSET = {
    500: (0, -3),
    501: (0, 3),
    535: (-3, -3),
    536: (0, -2),
}
POI_ICONS = { ctype: open_pil_image(f"icons/construct/{ctype}.png") for ctype in POI_ICON_SCALE.keys() }
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

ATTRIBUTE_IMAGES = { k: open_pil_image(f"icons/attribute/{k.value}.png") for k in Attribute.__members__.values() }
CONDITION_IMAGES = { k: open_pil_image(f"icons/condition/{k.value}.png") for k in Condition.__members__.values() }
SUBICON_IMAGES = { **ATTRIBUTE_IMAGES, **CONDITION_IMAGES }

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
        return ctype1 // 100 == ctype2 // 100   # DLC建筑必须前三位完全相同才共用图标
    else:
        return ctype1 // 1000 == ctype2 // 1000


@dataclass
class SubPoiInfo:
    ctypes: set[int]    # 包含该子图标的POI类型
    image: Image.Image  # 带子图标的POI图像

@dataclass
class PoiCategoryInfo:
    base_image: Image.Image     # 不包含子图标的基础图像
    subtypes: dict[Attribute | Condition, SubPoiInfo]  # 子图标对应的图像和带子图标的POI类型
    resized_images: dict[tuple[int, int], Image.Image] = field(default_factory=dict)

    def get_resized_image(self, size: tuple[int, int]) -> Image.Image:
        if size not in self.resized_images:
            self.resized_images[size] = self.base_image.resize(size, resample=PIL_RESAMPLE_METHOD)
        return self.resized_images[size]


@dataclass
class MapPatternMatchResult:
    pattern: MapPattern
    nightlord: int | None
    score: int
    error: int


@dataclass
class MapDetectParam:
    map_region: tuple[int] | None = None
    img: np.ndarray | None = None
    earth_shifting: int | None = None
    do_match_full_map: bool = False
    do_match_earth_shifting: bool = False
    do_match_pattern: bool = False
    hdr_processing_enabled: bool = False

@dataclass
class MapDetectResult:
    img: np.ndarray | None = None
    is_full_map: bool = None
    earth_shifting: int | None = None
    earth_shifting_score: float | None = None
    patterns: list[dict] = None
    overlay_images: list[Image.Image] = None


class MapDetector:  
    def __init__(self):
        # 地图信息
        self.info = load_map_info(
            get_data_path('csv/map_patterns.csv'),
            get_data_path('csv/constructs.csv'),
            get_data_path('csv/names.csv'),
            get_data_path('csv/positions.csv'),
        )

        # 初始化POI信息
        all_poi_construct_types = set()
        for es in self.info.all_earth_shiftings:
            for nl in self.info.all_nightlords:
                all_poi_construct_types.update(self.info.all_poi_construct_type.get((es, nl), set()))

        self.all_poi_images: dict[int, Image.Image] = {}  # 所有POI类型对应图标
        self.poi_cate_info: dict[int, PoiCategoryInfo] = {}  # POI大类别对应图标信息
        for ctype in all_poi_construct_types:
            if poi_key := get_poi_key(ctype):
                if poi_key not in self.poi_cate_info:
                    self.poi_cate_info[poi_key] = PoiCategoryInfo(
                        base_image=self._get_poi_image(ctype, with_subicon=False),
                        subtypes={},
                    )
                info = self.poi_cate_info[poi_key]
                subicon = CTYPE_SUBICON_MAP.get(ctype)
                if subicon not in info.subtypes:
                    info.subtypes[subicon] = SubPoiInfo(
                        ctypes=set(),
                        image=self._get_poi_image(ctype, with_subicon=True),
                    )
                info.subtypes[subicon].ctypes.add(ctype)
                self.all_poi_images[ctype] = info.subtypes[subicon].image
        # 无建筑
        self.all_poi_images[0] = Image.new("RGBA", STD_POI_SIZE, (0, 0, 0, 0))
        self.poi_cate_info[0] = PoiCategoryInfo(
            base_image=self.all_poi_images[0],
            subtypes={ None: SubPoiInfo(
                ctypes={0},
                image=self.all_poi_images[0],
            )},
        )

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
            icon = icon.resize((int(icon.size[0] * icon_scale), int(icon.size[1] * icon_scale)), resample=PIL_RESAMPLE_METHOD)
            iw, ih = icon.size
            target_img.alpha_composite(icon, (cx - iw // 2, cy - ih // 2))
            target_img = target_img.resize((int(MATCH_NIGHTLORD_SIZE[0] * 0.2), int(MATCH_NIGHTLORD_SIZE[1] * 0.2)), resample=PIL_RESAMPLE_METHOD)
            # display_pil_image(target_img, None)
            h, w = target_img.size
            target_img = target_img.crop((int(w*0.3), int(h*0.3), int(w*0.7), int(h*0.7)))
            nightlords[i] = (nightlord, np.array(target_img)[..., :3])
        self.nightlord_icons: list[tuple[None | int, np.ndarray]] = nightlords
            
        
    def _match_full_map(self, img: np.ndarray) -> float:
        config = Config.get()
        img = img[-int(img.shape[0]*0.22):, :int(img.shape[1]*0.22)]
        img = cv2.resize(img, CHECK_FULL_MAP_STD_SIZE, interpolation=CV2_RESIZE_METHOD)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        circles = []
        for thres in config.full_map_hough_circle_thres:
            res = cv2.HoughCircles(
                gray, 
                cv2.HOUGH_GRADIENT, 
                dp=1, 
                minDist=20,
                param1=thres,
                param2=30, 
                minRadius=int(img.shape[0] * 0.4), 
                maxRadius=int(img.shape[0] * 0.5)
            )
            if res is not None:
                circles.extend(res)
        error = float('inf')
        if circles:
            cx, cy, cr = sorted(list(circles[0]), key=lambda x: x[2], reverse=True)[0]
            # cv2.circle(img, (int(cx), int(cy)), int(cr), (0, 255, 0), 2)
            # cv2.circle(img, (int(cx), int(cy)), 2, (0, 0, 255), 3)
            # cv2.imwrite("sandbox/full_map_test.jpg", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
            error = abs(cr - img.shape[0] * 0.425) ** 2
        debug(f"MapDetector: Full map match error: {error:.4f}")
        return error
    
    def _match_earth_shifting(self, img: np.ndarray) -> tuple[int, float]:
        t = time.time()
        img = cv2.resize(img, MATCH_EARTH_SHIFTING_SIZE, interpolation=CV2_RESIZE_METHOD)
        x, y, w, h = MATCH_EARTH_SHIFTING_REGION
        img = img[y:y+h, x:x+w].astype(int)
        best_map_id, best_score = None, float('inf')
        offset, stride = MATCH_EARTH_SHIFTING_OFFSET_AND_STRIDE
        min_scale, max_scale, scale_num = MATCH_EARTH_SHIFTING_SCALES
        for map_id, map_img in MAP_BGS.items():
            score = float('inf')
            for scale in np.linspace(min_scale, max_scale, scale_num, endpoint=True):
                size = (int(MATCH_EARTH_SHIFTING_SIZE[0] * scale), int(MATCH_EARTH_SHIFTING_SIZE[1] * scale))
                map_resized = cv2.resize(map_img, size, interpolation=CV2_RESIZE_METHOD).astype(int)
                for dx in range(-offset, offset+1, stride):
                    for dy in range(-offset, offset+1, stride):
                        map_shifted = map_resized[y+dy:y+h+dy, x+dx:x+w+dx]
                        diff = np.abs((img - map_shifted))
                        diff[diff > 100] = 0
                        diff = np.linalg.norm(diff, axis=2)
                        cur_score = np.median(diff)
                        score = min(score, cur_score)
            # print(f"map {map_id} score: {score:.4f}")
            if score < best_score:
                best_score = score
                best_map_id = map_id
        info(f"MapDetector: Match earth shifting: best map {best_map_id} score {best_score:.4f}, time cost: {time.time() - t:.4f}s")
        return best_map_id, best_score
    
    def _match_nightlord(self, img: np.array) -> tuple[int | None, float]:
        t = time.time()
        img = cv2.resize(img, MATCH_NIGHTLORD_SIZE, interpolation=CV2_RESIZE_METHOD)
        h, w = img.shape[0], img.shape[1]
        img = img[-int(h*0.15):-int(h*0.05), int(w*0.06):int(w*0.16)]

        best_nightlord, best_score = None, float('inf')
        
        for nightlord, icon in self.nightlord_icons:
            match_result, score = match_template(
                img, 
                icon, 
                MATCH_NIGHTLORD_SCALES
            )
            # print(f"nightlord {nightlord} score: {score:.4f}")
            if score < best_score:
                best_score = score
                best_nightlord = nightlord

        info(f"MapDetector: Match nightlord: best nightlord {best_nightlord} score {best_score:.4f}, time cost: {time.time() - t:.4f}s")
        return best_nightlord, best_score


    def _get_poi_image(self, construct_type: int, with_subicon: bool = False) -> Image.Image:
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

    def _match_poi(self, map_img: np.ndarray, map_bg: np.ndarray, pos: Position, earth_shifting: int, nightlord: int | None = None) -> tuple[int, float]:
        img = map_img[
            pos[1]-STD_POI_SIZE[1]//2:pos[1]-STD_POI_SIZE[1]//2+STD_POI_SIZE[1],
            pos[0]-STD_POI_SIZE[0]//2:pos[0]-STD_POI_SIZE[1]//2+STD_POI_SIZE[0],
        ]
        bg = map_bg[
            pos[1]-STD_POI_SIZE[1]//2:pos[1]-STD_POI_SIZE[1]//2+STD_POI_SIZE[1],
            pos[0]-STD_POI_SIZE[0]//2:pos[0]-STD_POI_SIZE[1]//2+STD_POI_SIZE[0],
        ]
        

        # 判断建筑类型
        DOWNSAMPLE_SIZE = (16, 16)
        MAX_OFFSET = 4
        OFFSET_STRIDE = 2
        SCALE_RANGE = (0.9, 1.1, 5)

        img_for_poi = cv2.resize(img, DOWNSAMPLE_SIZE, interpolation=CV2_RESIZE_METHOD)
        h, w, _ = img_for_poi.shape
        h_min, h_max, w_min, w_max = int(h*0.2), int(h*0.8), int(w*0.2), int(w*0.6)
        img_for_poi = img_for_poi[h_min:h_max, w_min:w_max]
        bg = Image.fromarray(bg).convert("RGBA")

        best_poi_key = None
        best_poi_key_score = float('inf')

        # 收集该位置可能出现的POI类型
        nightlords = [nightlord] if nightlord is not None else self.info.all_nightlords
        possible_ctypes = set()
        for nl in nightlords:
            possible_ctypes.update(self.info.possible_poi_types.get((earth_shifting, nl, pos), set()))

        # print("pos:", pos, "possible ctypes:", possible_ctypes)
        for poi_key, info in self.poi_cate_info.items():
            t = time.time()
            if not any(match_prefix(ctype, poi_key) for ctype in possible_ctypes):
                continue    # 仅匹配该位置可能出现的POI类型
            
            target_imgs = []
            for dx in range(-MAX_OFFSET, MAX_OFFSET+1, OFFSET_STRIDE):
                for dy in range(-MAX_OFFSET, MAX_OFFSET+1, OFFSET_STRIDE):
                    for s in np.linspace(SCALE_RANGE[0], SCALE_RANGE[1], SCALE_RANGE[2], endpoint=True):
                        size = (int(STD_POI_SIZE[0] * s), int(STD_POI_SIZE[1] * s))
                        resized_poi_icon = info.get_resized_image(size)
                        poi_img = bg.copy()
                        poi_img.alpha_composite(resized_poi_icon, (dx, dy))
                        poi_img = np.array(poi_img)[..., :3]
                        poi_img = cv2.resize(poi_img, DOWNSAMPLE_SIZE, interpolation=CV2_RESIZE_METHOD)
                        poi_img = poi_img[h_min:h_max, w_min:w_max]
                        target_imgs.append(poi_img)

            target_imgs = np.array(target_imgs).astype(np.float32)
            diffs = np.mean((target_imgs - img_for_poi.astype(np.float32)) ** 2, axis=(1, 2, 3))
            min_idx = np.argmin(diffs)
            poi_key_score = diffs[min_idx]
            if poi_key_score < best_poi_key_score:
                best_poi_key_score = poi_key_score
                best_poi_key = poi_key

            # best_img = target_imgs[min_idx].astype(np.uint8)
            # vis = np.concatenate([img_for_poi, best_img], axis=1)
            # display_cv2_image(vis, None)
            # if pos == (270, 615):
            #     cv2.imwrite(f"sandbox/debug/{poi_key}.jpg", cv2.cvtColor(vis, cv2.COLOR_RGB2BGR))
            # print(f"{pos} poi category {poi_key} match score: {poi_key_score:.4f}, time cost: {time.time() - t:.4f}s")

        # print(f"Best {pos} poi category:", best_poi_key, "score:", best_poi_key_score)

        # 判断子图标类型
        DOWNSAMPLE_SIZE = (64, 64)
        SCALE_RANGE = (0.9, 1.1, 5)

        img_for_subicon = cv2.resize(img, DOWNSAMPLE_SIZE, interpolation=CV2_RESIZE_METHOD)
        h, w, _ = img_for_subicon.shape
        img_for_subicon = img_for_subicon[int(h*0.4):, int(w*0.4):]
        img_for_subicon = cv2.GaussianBlur(img_for_subicon, (3, 3), 0)

        best_subicon = None
        best_subicon_score = float('inf')

        for subicon, info in self.poi_cate_info[best_poi_key].subtypes.items():
            if not subicon:
                continue
            t = time.time()
            subicon_img = SUBICON_IMAGES[subicon]
            for s in np.linspace(SCALE_RANGE[0], SCALE_RANGE[1], SCALE_RANGE[2], endpoint=True):
                size = (int(DOWNSAMPLE_SIZE[0] * s * 0.3), int(DOWNSAMPLE_SIZE[1] * s * 0.3))
                target_img = subicon_img.resize(size, resample=Image.Resampling.NEAREST).convert("RGB")
                target_img = np.array(target_img).astype(np.uint8)
                target_img = cv2.GaussianBlur(target_img, (3, 3), 0)
                th, tw = target_img.shape[0], target_img.shape[1]
                target_img = target_img[int(th*0.1):int(th*0.9), int(tw*0.1):int(tw*0.9)]
                match_result, match_val = match_template(
                    img_for_subicon,
                    target_img,
                    scales=(1.0, 1.0, 1)
                )
                if match_val < best_subicon_score:
                    best_subicon_score = match_val
                    best_subicon = subicon
                
                # if abs(1.0 - s) < 1e-3:
                #     vis = img_for_subicon.copy()
                #     vis[:size[0], :size[1], :] = target_img
                #     display_cv2_image(vis, None)
                # print(f"subicon {subicon} {s:.2f}x match score: {match_val:.4f}, time cost: {time.time() - t:.4f}s")

        if None in self.poi_cate_info[best_poi_key].subtypes:
            if best_subicon_score > Config.get().subicon_template_match_threshold:
                best_subicon = None
        
        # print("Best subicon", best_subicon, "score:", best_subicon_score)

        best_ctype = sorted(list(self.poi_cate_info[best_poi_key].subtypes.get(best_subicon).ctypes))[0]
        return best_ctype, best_poi_key_score * best_subicon_score

    def _match_map_pattern(self, img: np.ndarray, earth_shifting: int, topk: int) -> list[MapPatternMatchResult]:
        assert earth_shifting is not None, "earth_shifing should be provided when matching map pattern"

        t = time.time()
        img = cv2.resize(img, STD_MAP_SIZE, interpolation=CV2_RESIZE_METHOD)

        # 识别夜王
        nightlord, _ = self._match_nightlord(img)

        # 校准偏移
        map_bg = cv2.resize(MAP_BGS[earth_shifting], STD_MAP_SIZE, interpolation=CV2_RESIZE_METHOD)
        try:
            align_t = time.time()
            ALIGN_REGION = (
                int(STD_MAP_SIZE[0] * 0.2),
                int(STD_MAP_SIZE[1] * 0.2),
                int(STD_MAP_SIZE[0] * 0.6),
                int(STD_MAP_SIZE[1] * 0.6),
            )
            img = align_image(img, map_bg, ALIGN_REGION)
            info(f"MapDetector: Align map image time cost: {time.time() - align_t:.4f}s")
        except Exception as e:
            warning(f"MapDetector: Align map image failed: {e}")

        # 识别POI
        poi_result: dict[Position, int] = {}
        poi_result_img = img.copy()    # for debug

        all_poi_pos = set() # 收集所有待匹配POI点
        nightlords = [nightlord] if nightlord is not None else self.info.all_nightlords
        for nl in nightlords:
            all_poi_pos.update(self.info.all_poi_pos.get((earth_shifting, nl), set()))

        ratio = Config.get().poi_match_sample_ratio_w_nightlord if nightlord is not None else Config.get().poi_match_sample_ratio_wo_nightlord
        sample_num = max(8, int(len(all_poi_pos) * ratio))  # 最少采样8个POI点
        all_poi_pos = list(all_poi_pos)
        random.shuffle(all_poi_pos)

        for x, y in sorted(all_poi_pos[:sample_num]):
            ctype, score = self._match_poi(img, map_bg, (x, y), earth_shifting, nightlord)
            poi_result[(x, y)] = ctype

            # 绘制调试图
            paste_cv2(poi_result_img, np.array(self.all_poi_images[ctype])[..., :3], (x-STD_POI_SIZE[0]//2, y-STD_POI_SIZE[1]//2))
            cv2.circle(poi_result_img, (x, y), 2, (255, 0, 0), 3)

        # 保存结果用于调试
        cv2.imwrite(get_appdata_path(f"map.jpg"), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
        cv2.imwrite(get_appdata_path(f"map_poi_result.jpg"), cv2.cvtColor(poi_result_img, cv2.COLOR_RGB2BGR))

        # 匹配地图模式
        EMPTY_CONSTRUCTION = Construct(type=0, pos=0, is_display=False)
        results: list[MapPatternMatchResult] = []
        for pattern in self.info.patterns:
            if pattern.earth_shifting != earth_shifting:
                continue
            if nightlord is not None and pattern.nightlord != nightlord:
                continue
            score, error = 0, 0
            for pos, ctype in poi_result.items():
                expect_ctype = pattern.pos_constructions.get(pos, EMPTY_CONSTRUCTION).type
                if expect_ctype not in self.all_poi_images:
                    expect_ctype = 0

                subicon = CTYPE_SUBICON_MAP.get(ctype)
                expect_subicon = CTYPE_SUBICON_MAP.get(expect_ctype)

                if not has_same_base_icon(ctype, expect_ctype):   # 建筑类型不符合
                    if subicon == expect_subicon:
                        score += 1      # 子图标符合
                        error += 3
                    else:
                        score += 0
                        error += 10
                else:
                    if subicon == expect_subicon:
                        score += 10     # 完全符合 
                        error += 0
                    elif subicon or expect_subicon:
                        score += 0  # 一个有子图标一个没有
                        error += 10
                    else:
                        score += 3      # 子图标不符合
                        error += 1

            # info(f"pattern {pattern.id} match score: {score} error: {error}")
            results.append(MapPatternMatchResult(
                pattern=pattern,
                nightlord=nightlord,
                score=score,
                error=error,
            ))

        # 使用Error最小的结果
        results = sorted(results, key=lambda x: (x.error, -x.score))
        best_patterns_by_error = results[:topk]
        info(f"Match map pattern: return {[p.pattern.id for p in best_patterns_by_error]}, time cost: {time.time() - t:.4f}s")
        return best_patterns_by_error


    def _draw_overlay_image(self, match_result: MapPatternMatchResult, draw_size: tuple[int, int], result_index: int) -> Image.Image:
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
        BOSS1_ICON = open_with_draw_size("icons/boss1.png", (24, 24))
        BOSS2_ICON = open_with_draw_size("icons/boss2.png", (24, 24))
        CARRIAGE_ICON = open_with_draw_size("icons/carriage.png", (32, 32))
        BOSS1_CTYPES = [
            46510, 46570, 46590, 46620, 46650, 46690,
            46710, 46720, 46770, 46810, 46820, 46860,
            46880, 46910, 46950, 45510, 46550, 
        ]
        BOSS2_CTYPES = [
            46520, 46530, 46540, 46560, 46630, 46640,
            46660, 46670, 46680, 46740, 46870, 46580,
        ]

        NIGHT_CIRCLE_ICON = open_with_draw_size("icons/night_circle.png", (112, 112))

        MAIN_CASTLE_UPPERFLOOR_POS = scale_size((328, 409))
        MAIN_CASTLE_BASEMENT_POS = scale_size((355, 409))

        ROTREW_ICON = open_with_draw_size("icons/rot_rew.png", (37, 37))
        ROTREW_POS = {
            1046300590: scale_size((477, 583)),
            1057300590: scale_size((600, 452)),
            1047300590: scale_size((423, 500)),
        }

        FONT_SIZE_LARGE = scale_size(16)
        FONT_SIZE_SMALL = scale_size(14)
        OUTLINE_COLOR = (0, 0, 0, 255)
        OUTLINE_W_LARGE = max(1, scale_size(2))
        OUTLINE_W_SMALL = max(1, scale_size(2))

        EVENT_ICON = open_with_draw_size("icons/event.png", (45, 45))

        # 大空洞神授塔BOSS对应位置索引
        TGH_FLOOR_BOSS_POS_INDEX = {
            1111: ('RB', 1),
            1112: ('RB', 2),
            1113: ('RB', 3),
            1114: ('LT', 1),
            1115: ('LT', 2),
            1116: ('LT', 3),
        }

        # 开始绘制
        img = Image.new("RGBA", draw_size, (0, 0, 0, 0))
        texts, icons = [], []

        # day1 boss
        x, y = scale_size(pattern.day1_pos)
        name = get_name(pattern.day1_boss) or "未知BOSS"
        extra_name = get_name(pattern.day1_extra_boss) if pattern.day1_extra_boss != -1 else None
        icons.append(((x, y), NIGHT_CIRCLE_ICON))
        texts.append(((x, y + scale_size(40)), f"Day1 {name}", FONT_SIZE_LARGE, (210, 210, 255, 255), OUTLINE_W_LARGE, OUTLINE_COLOR))
        if extra_name: texts.append(((x, y + scale_size(60)), f"额外Boss:{extra_name}", 
                                    FONT_SIZE_LARGE, (255, 255, 255, 255), OUTLINE_W_LARGE, OUTLINE_COLOR))

        # day2 boss
        x, y = scale_size(pattern.day2_pos)
        name = get_name(pattern.day2_boss) or "未知BOSS"
        extra_name = get_name(pattern.day2_extra_boss) if pattern.day2_extra_boss != -1 else None
        icons.append(((x, y), NIGHT_CIRCLE_ICON))
        texts.append(((x, y + scale_size(40)), f"Day2 {name}", FONT_SIZE_LARGE, (210, 210, 255, 255), OUTLINE_W_LARGE, OUTLINE_COLOR))
        if extra_name: texts.append(((x, y + scale_size(60)), f"额外Boss:{extra_name}", 
                                    FONT_SIZE_LARGE, (255, 255, 255, 255), OUTLINE_W_LARGE, OUTLINE_COLOR))
            
        # 大空洞第二天缩圈位置
        day2_lefttop = pattern.day2_pos_idx == 12000
        IN_CIRCLE_COLOR = (200, 255, 200, 255)
        OUT_CIRCLE_COLOR = (255, 200, 200, 255)
            
        for pos, construct in pattern.pos_constructions.items():
            pos = scale_size(pos)
            x, y = pos
            ctype = construct.type

            def match(*prefixes) -> bool:
                s = str(ctype)
                for prefix in prefixes:
                    if s.startswith(str(prefix)):
                        return True
                return False
            
            def process_underground_name(name: str):
                if construct.is_underground:
                    return '↓' + name
                return name

            # boss
            if match(45, 46) and not match(460) and (ctype == 45510 or ctype // 1000 != 45) and ctype not in (46780,):
                name = get_name(ctype)
                if pos == MAIN_CASTLE_UPPERFLOOR_POS:   
                    y -= scale_size(10)
                    x += scale_size(13)
                    name = '楼顶:' + name
                elif pos == MAIN_CASTLE_BASEMENT_POS:   
                    y += scale_size(10)
                    x -= scale_size(13)
                    name = '地下室:' + name
                else: 
                    y += scale_size(15)
                    if ctype in BOSS1_CTYPES:
                        icons.append(((x, y - scale_size(20)), BOSS1_ICON))
                    elif ctype in BOSS2_CTYPES:
                        icons.append(((x, y - scale_size(20)), BOSS2_ICON))
                color = (255, 255, 255, 255) if not construct.is_underground else (200, 200, 255, 255)
                if name:
                    texts.append(((x, y), process_underground_name(name), FONT_SIZE_LARGE, color, OUTLINE_W_LARGE, OUTLINE_COLOR))
            
            # 主城类型
            if match(494) and ctype != 49400:
                y -= scale_size(30)
                x -= scale_size(15)
                texts.append(((x, y), get_name(ctype), FONT_SIZE_LARGE, (255, 255, 0, 255), OUTLINE_W_LARGE, OUTLINE_COLOR))
            # 主城类型（大空洞）
            if match(5358, 5359, 5367, 5368):
                y += scale_size(25)
                x += scale_size(5)
                color = IN_CIRCLE_COLOR if match(536) ^ day2_lefttop else OUT_CIRCLE_COLOR 
                texts.append(((x, y), get_name(ctype), FONT_SIZE_LARGE, color, OUTLINE_W_LARGE, OUTLINE_COLOR))
                # 下水道类型
                for p2, c2 in pattern.pos_constructions.items():
                    if match(536) and c2.type in (53700, 53710, 53720) \
                    or match(535) and c2.type in (53600, 53610):
                        y += scale_size(20)
                        texts.append(((x, y), '↓' + get_name(c2.type), FONT_SIZE_LARGE, color, OUTLINE_W_LARGE, OUTLINE_COLOR))
            # 法师塔
            if match(400, 5110):
                texts.append(((x, y), get_name(ctype), FONT_SIZE_SMALL, (210, 255, 200, 255), OUTLINE_W_SMALL, OUTLINE_COLOR))
            # 马车
            if match(4500, 4501, 51150):
                icons.append(((x, y), CARRIAGE_ICON))
            # POI
            if match(
                30, 32, 34, 38, 
                500, 501, 524, 525, 
            ):
                color = (200, 220, 150, 255) if not construct.is_underground else (250, 200, 250, 255)
                y += scale_size(15)
                texts.append(((x, y), process_underground_name(get_name(ctype)), FONT_SIZE_SMALL, color, OUTLINE_W_SMALL, OUTLINE_COLOR))
            # 特殊事件（癫火塔除外）
            if 200 <= ctype // 100 <= 215:
                icons.append(((x, y), EVENT_ICON))
                y += scale_size(15)
                texts.append(((x, y), get_event_text(pattern), FONT_SIZE_SMALL, (255, 200, 200, 255), OUTLINE_W_SMALL, OUTLINE_COLOR))
            # 玛莉卡教堂(下层)
            if match(51) and construct.is_underground:
                y += scale_size(15)
                texts.append(((x, y), process_underground_name("玛莉卡教堂"), FONT_SIZE_SMALL, (200, 255, 255, 255), OUTLINE_W_SMALL, OUTLINE_COLOR))
            # 神授塔BOSS
            if construct.pos_index in TGH_FLOOR_BOSS_POS_INDEX:
                floor_pos, floor_num = TGH_FLOOR_BOSS_POS_INDEX[construct.pos_index]
                x, y = scale_size((100, 280) if floor_pos == 'LT' else (680, 530))
                y += scale_size((3 - floor_num) * 20)
                color = IN_CIRCLE_COLOR if (day2_lefttop ^ (floor_pos == 'RB')) else OUT_CIRCLE_COLOR
                texts.append(((x, y), f"{floor_num}F: {get_name(ctype)}", 
                                FONT_SIZE_LARGE, color, OUTLINE_W_LARGE, OUTLINE_COLOR))

        # 宝藏
        treasure_id = pattern.treasure * 10 + pattern.earth_shifting
        try:
            treasure = open_with_draw_size(f"treasures/treasure_{treasure_id}.png", (800, 800))
            icons.append((scale_size((375, 375)), treasure))
        except FileNotFoundError:
            warning(f"Treasure image not found: treasure_{treasure_id}.png")

        # 癫火塔
        if pattern.event_value == 3080:
            frenzy = open_with_draw_size(f"frenzy/Frenzy_{pattern.evpat_flag}.png", (800, 800))
            icons.append((scale_size((375, 375)), frenzy))

        # 腐败庇佑
        if pos := ROTREW_POS.get(pattern.rot_rew):
            icons.append((pos, ROTREW_ICON))
            texts.append(((pos[0], pos[1] + scale_size(20)), "庇佑", FONT_SIZE_SMALL, (255, 200, 200, 255), OUTLINE_W_SMALL, OUTLINE_COLOR))

        # 说明文本
        text = f"#{pattern.id}"
        if match_result.error is not None:
            text += f" (E:{match_result.error})"
        text += f"    {get_name(pattern.nightlord + 100000)}"
        if match_result.nightlord is None:
            text += " (隐藏夜王)"
        if event_text := get_event_text(pattern):
            text += f"    特殊事件: {event_text}"
        texts.append((scale_size((20, 10)), text, scale_size(24), (255, 255, 255, 255), scale_size(3), OUTLINE_COLOR, 'lt'))

        # 大空洞第二天缩圈位置
        if pattern.earth_shifting == 4:
            text = "左上" if day2_lefttop else "右下"
            text = f"Day2第一次缩圈位置：{text}"
            texts.append((scale_size((20, 38)), text, scale_size(24), (255, 255, 255, 255), scale_size(3), OUTLINE_COLOR, 'lt'))

        for icon in icons:  draw_icon(img, *icon)
        for text in texts:  draw_text(img, *text)

        info(f"Draw overlay image size: {draw_size} time cost: {time.time() - t:.4f}s")

        # 保存结果用于调试
        img.convert('RGB').save(get_appdata_path(f"map_overlay_result_{result_index}.jpg"))

        return img

    def detect(self, sct: MSSBase, param: MapDetectParam | None) -> MapDetectResult:
        config = Config.get()
        ret = MapDetectResult()
        if param is None or param.map_region is None:
            return ret
        
        if param.img is None:
            # 根据参数选择图像处理方式
            processing = 'normalize' if param.hdr_processing_enabled else 'none'
            img = grab_region(sct, param.map_region, processing=processing)
            img = np.array(img)
        else:
            img = param.img
        ret.img = img

        # 判断是否是全图
        if param.do_match_full_map:
            full_map_error = self._match_full_map(img)
            ret.is_full_map = full_map_error <= config.full_map_error_threshold

        # 判断特殊地形
        if param.do_match_earth_shifting:
            earth_shifting, earth_shifting_score = self._match_earth_shifting(img)
            if earth_shifting_score > config.earth_shifting_error_threshold:
                earth_shifting = None
            ret.earth_shifting = earth_shifting
            ret.earth_shifting_score = earth_shifting_score

        # 地图模式匹配
        if param.do_match_pattern:
            results = self._match_map_pattern(img, param.earth_shifting, config.map_pattern_match_topk)

            # 决定信息绘制大小
            if config.fixed_map_overlay_draw_size is not None:
                draw_size = tuple(config.fixed_map_overlay_draw_size)
            elif config.map_overlay_draw_size_ratio is not None:
                draw_size = (
                    int(param.map_region[2] * config.map_overlay_draw_size_ratio),
                    int(param.map_region[3] * config.map_overlay_draw_size_ratio),
                )
            else:
                draw_size = STD_MAP_SIZE

            ret.patterns = []
            ret.overlay_images = []
            for i, result in enumerate(results):
                try:
                    info(f"MapDetector: Start to draw overlay image for pattern {result.pattern.id}")
                    overlay_img = self._draw_overlay_image(result, draw_size, i)
                    ret.overlay_images.append(overlay_img)
                    ret.patterns.append(result.pattern)
                except Exception as e:
                    error(f"MapDetector: Draw overlay image of pattern {result.pattern.id} failed: {e}")

        return ret


