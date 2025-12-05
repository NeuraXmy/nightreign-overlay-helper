import cv2
import numpy as np
from dataclasses import dataclass
from PIL import Image
import time
from mss.base import MSSBase

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
)


CV2_RESIZE_METHOD = cv2.INTER_CUBIC
PIL_RESAMPLE_METHOD = Image.Resampling.BICUBIC

def open_pil_image(path: str, size: tuple[int, int] | None = None) -> Image.Image:
    image = Image.open(get_data_path(path)).convert("RGBA")
    if size is not None:
        image = image.resize(size, resample=PIL_RESAMPLE_METHOD)
    return image

def open_cv2_image(path: str, size: tuple[int, int] | None = None) -> np.ndarray:
    image = cv2.cvtColor(cv2.imread(get_data_path(path)), cv2.COLOR_BGR2RGB)
    if size is not None:
        image = cv2.resize(image, size, interpolation=CV2_RESIZE_METHOD)
    return image


CHECK_FULL_MAP_STD_SIZE = (100, 100)

PREDICT_EARTH_SHIFTING_SIZE = (100, 100)
PREDICT_EARTH_SHIFTING_SIZE_REGION = (
    int(PREDICT_EARTH_SHIFTING_SIZE[0] * 0.2),
    int(PREDICT_EARTH_SHIFTING_SIZE[1] * 0.2),
    int(PREDICT_EARTH_SHIFTING_SIZE[0] * 0.6),
    int(PREDICT_EARTH_SHIFTING_SIZE[1] * 0.6),
)
PREDICT_EARTH_SHIFTING_OFFSET_AND_STRIDE = (5, 1)
PREDICT_EARTH_SHIFTING_SCALES = (0.95, 1.05, 7)
MAP_BGS = { i : open_cv2_image(f"maps/{i}.jpg") for i in range(7) if i != 4 }

POI_ICON_SCALE = { 30: 0.35, 32: 0.5, 34: 0.4, 37: 0.4, 38: 0.3, 40: 0.4, 41: 0.38, }
POI_ICONS = { ctype: open_pil_image(f"icons/construct/{ctype}.png") for ctype in POI_ICON_SCALE.keys() }
STD_POI_SIZE = (45, 45)
ATTRIBUTE_ICONS = [open_pil_image(f"icons/attribute/{i}.png") for i in range(4)]
CONDITION_ICONS = [open_pil_image(f"icons/condition/{i}.png") for i in range(7)]
POI_SUBICON_MAP = {
    30301: ATTRIBUTE_ICONS[1],  # 结晶人要塞-魔
    32101: ATTRIBUTE_ICONS[0],  # 红狮子营地-火
    32102: ATTRIBUTE_ICONS[2],  # 骑士营地-雷
    32200: ATTRIBUTE_ICONS[0],  # 战车营地-火
    32201: CONDITION_ICONS[3],  # 癫火营地-癫火
    34001: CONDITION_ICONS[0],  # 鲜血遗迹-出血
    34002: CONDITION_ICONS[1],  # 萨米尔遗迹-冻伤
    34003: ATTRIBUTE_ICONS[3],  # 白金遗迹-圣
    34100: CONDITION_ICONS[5],  # 调香师遗迹-中毒
    34101: CONDITION_ICONS[5],  # 堕落调香师遗迹-中毒
    34102: ATTRIBUTE_ICONS[1],  # 法师遗迹-魔
    34103: CONDITION_ICONS[1],  # 白金射手遗迹-冻伤
    34104: CONDITION_ICONS[6],  # 卢恩熊遗迹-睡眠
    34200: CONDITION_ICONS[2],  # 蚯蚓脸遗迹-咒死
    34300: ATTRIBUTE_ICONS[2],  # 兽人遗迹-雷
    38000: ATTRIBUTE_ICONS[3],  # 使者教堂-圣
    38100: ATTRIBUTE_ICONS[0],  # 火焰教堂-火
}


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
    pattern: MapPattern = None
    pattern_score: int = None
    overlay_image: Image.Image = None


class MapDetector:  
    def __init__(self):
        # 地图信息
        self.info = load_map_info(
            get_data_path('csv/map_patterns.csv'),
            get_data_path('csv/constructs.csv'),
            get_data_path('csv/names.csv'),
            get_data_path('csv/positions.csv'),
        )
        # 处理出所有POI的图标，以及具有独立图标的POI
        self.all_unique_poi_image_ctype: list[int] = []
        self.all_poi_images: dict[int, Image.Image] = {}
        self.all_unique_poi_images: dict[int, Image.Image] = {}
        for ctype in self.info.all_poi_construct_type:
            same_image_ct = None
            for ct in self.all_unique_poi_image_ctype:
                if ctype // 1000 == ct // 1000 \
                    and POI_SUBICON_MAP.get(ctype) == POI_SUBICON_MAP.get(ct):
                    same_image_ct = ct
                    break
            if same_image_ct is None:
                self.all_unique_poi_image_ctype.append(ctype)
                self.all_unique_poi_images[ctype] = self._get_poi_image(ctype)
                self.all_poi_images[ctype] = self.all_unique_poi_images[ctype]
            else:
                self.all_poi_images[ctype] = self.all_unique_poi_images[same_image_ct]
        

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
        img = cv2.resize(img, PREDICT_EARTH_SHIFTING_SIZE, interpolation=CV2_RESIZE_METHOD)
        x, y, w, h = PREDICT_EARTH_SHIFTING_SIZE_REGION
        img = img[y:y+h, x:x+w].astype(int)
        best_map_id, best_score = None, float('inf')
        offset, stride = PREDICT_EARTH_SHIFTING_OFFSET_AND_STRIDE
        min_scale, max_scale, scale_num = PREDICT_EARTH_SHIFTING_SCALES
        for map_id, map_img in MAP_BGS.items():
            score = float('inf')
            for scale in np.linspace(min_scale, max_scale, scale_num, endpoint=True):
                size = (int(PREDICT_EARTH_SHIFTING_SIZE[0] * scale), int(PREDICT_EARTH_SHIFTING_SIZE[1] * scale))
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
    
    def _get_poi_image(self, construct_type: int) -> Image.Image:
        x, y = STD_POI_SIZE[0] // 2, STD_POI_SIZE[1] // 2
        img = Image.new("RGBA", STD_POI_SIZE, (0, 0, 0, 0))
        if construct_type:
            icon = POI_ICONS[construct_type // 1000]
            icon_scale = POI_ICON_SCALE[construct_type // 1000]
            icon_size = (
                int(icon.size[0] * icon_scale * STD_MAP_SIZE[0] / 750),
                int(icon.size[1] * icon_scale * STD_MAP_SIZE[1] / 750),
            )
            icon = icon.resize(icon_size, resample=PIL_RESAMPLE_METHOD)
            icon_pos = (x - icon_size[0] // 2, y - icon_size[1] // 2)
            img.alpha_composite(icon, icon_pos)
            if construct_type in POI_SUBICON_MAP:
                subicon = POI_SUBICON_MAP[construct_type]
                subicon_size = (
                    int(STD_MAP_SIZE[0] * 0.0185), 
                    int(STD_MAP_SIZE[1] * 0.0185),
                )
                subicon = subicon.resize(subicon_size, resample=PIL_RESAMPLE_METHOD)
                subicon_pos = (
                    int(x - subicon_size[0] / 2 + STD_MAP_SIZE[0] * 0.016),
                    int(y + subicon_size[1] / 2 + STD_MAP_SIZE[1] * -0.001),
                )
                img.alpha_composite(subicon, subicon_pos)
        return img
    
    def _match_poi(self, map_img: np.ndarray, map_bg: np.ndarray, pos: Position) -> tuple[int, float]:
        img = map_img[
            pos[1]-STD_POI_SIZE[1]//2:pos[1]-STD_POI_SIZE[1]//2+STD_POI_SIZE[1],
            pos[0]-STD_POI_SIZE[0]//2:pos[0]-STD_POI_SIZE[1]//2+STD_POI_SIZE[0],
        ]
        bg = map_bg[
            pos[1]-STD_POI_SIZE[1]//2:pos[1]-STD_POI_SIZE[1]//2+STD_POI_SIZE[1],
            pos[0]-STD_POI_SIZE[0]//2:pos[0]-STD_POI_SIZE[1]//2+STD_POI_SIZE[0],
        ]

        DOWNSAMPLE_SIZE = (16, 16)
        MAX_OFFSET = 6
        OFFSET_STRIDE = 2

        img = cv2.resize(img, DOWNSAMPLE_SIZE, interpolation=CV2_RESIZE_METHOD)
        bg = Image.fromarray(bg).convert("RGBA")

        # t = Timer()
        best_ctype = None
        best_score = float('inf')
        for ctype, poi_img in self.all_unique_poi_images.items():
            ctype_score = float('inf')
            for dx in range(-MAX_OFFSET, MAX_OFFSET+1, OFFSET_STRIDE):
                for dy in range(-MAX_OFFSET, MAX_OFFSET+1, OFFSET_STRIDE):
                    img2 = bg.copy()
                    img2.alpha_composite(poi_img, (dx, dy))
                    img2 = cv2.cvtColor(np.array(img2), cv2.COLOR_RGBA2RGB)
                    img2 = cv2.resize(img2, DOWNSAMPLE_SIZE, interpolation=CV2_RESIZE_METHOD)
                    score = np.mean((img.astype(np.float32) - img2.astype(np.float32)) ** 2)
                    ctype_score = min(ctype_score, score)
            if ctype_score < best_score:
                best_score = ctype_score
                best_ctype = ctype
            # print(f"construct {ctype} match score: {ctype_score:.4f}")
            # display_cv2_image(img_rgb, None)
            # display_cv2_image(img2_rgb, None)
        # print("best:", best_ctype, best_val)
        # display_pil_image(all_poi_images[best_ctype], None)
        # t.print()
        return best_ctype, best_score

    def _match_map_pattern(self, img: np.ndarray, earth_shifting: int) -> tuple[MapPattern | None, int]:
        assert earth_shifting is not None, "earth_shifing should be provided when matching map pattern"

        if earth_shifting > 5:
            return None, 0

        t = time.time()
        img = cv2.resize(img, STD_MAP_SIZE, interpolation=CV2_RESIZE_METHOD)

        # 识别POI
        map_bg = cv2.resize(MAP_BGS[earth_shifting], STD_MAP_SIZE, interpolation=CV2_RESIZE_METHOD)
        poi_result: dict[Position, int] = {}
        poi_result_img = img.copy()    # for debug

        for x, y in sorted(self.info.all_poi_pos):
            ctype, score = self._match_poi(img, map_bg, (x, y))
            poi_result[(x, y)] = ctype
            paste_cv2(poi_result_img, np.array(self.all_unique_poi_images[ctype])[..., :3], (x-STD_POI_SIZE[0]//2, y-STD_POI_SIZE[1]//2))
            # info(f"pos {x},{y} match construct {ctype} with score {score:.4f}")

        # 保存结果用于调试
        cv2.imwrite(get_appdata_path(f"map.jpg"), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
        cv2.imwrite(get_appdata_path(f"map_poi_result.jpg"), cv2.cvtColor(poi_result_img, cv2.COLOR_RGB2BGR))

        # 匹配地图模式
        EMPTY_CONSTRUCTION = Construct(type=0, pos=0, is_display=False)
        best_pattern_by_score, best_score = None, 0
        best_pattern_by_error, best_error = None, 1e9
        for pattern in self.info.patterns:
            if pattern.earth_shifting != earth_shifting:
                continue
            score, error = 0, 0
            for pos, ctype in poi_result.items():
                expect_ctype = pattern.pos_constructions.get(pos, EMPTY_CONSTRUCTION).type
                subicon = POI_SUBICON_MAP.get(ctype)
                expect_subicon = POI_SUBICON_MAP.get(expect_ctype)
                if ctype // 1000 != expect_ctype // 1000:   # 建筑类型不符合
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
            if score > best_score:
                best_score = score
                best_pattern_by_score = pattern
            if error < best_error:
                best_error = error
                best_pattern_by_error = pattern

        # 使用Error最小的结果
        best_pattern = best_pattern_by_error
        info(f"Match map pattern: best pattern by score: #{best_pattern_by_score.id} score: {best_score}")
        info(f"Match map pattern: best pattern by error: #{best_pattern_by_error.id} error: {best_error}")
        info(f"Match map pattern: return pattern #{best_pattern.id}, time cost: {time.time() - t:.4f}s")
        return best_pattern, best_score


    def _draw_overlay_image(self, pattern: MapPattern | None, draw_size: tuple[int, int]) -> Image.Image:
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

        # 开始绘制
        img = Image.new("RGBA", draw_size, (0, 0, 0, 0))
        texts, icons = [], []

        if pattern:
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

            for pos, construct in pattern.pos_constructions.items():
                pos = scale_size(pos)
                x, y = pos
                ctype = construct.type
                # boss
                if ctype // 1000 in (45, 46) and ctype // 100 != 460 and (ctype == 45510 or ctype // 1000 != 45) and ctype not in (46780,):
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
                    if name:
                        texts.append(((x, y), name, FONT_SIZE_LARGE, (255, 255, 255, 255), OUTLINE_W_LARGE, OUTLINE_COLOR))
                # 主城类型
                if ctype // 100 == 494 and ctype != 49400:
                    y -= scale_size(30)
                    x -= scale_size(15)
                    texts.append(((x, y), get_name(ctype), FONT_SIZE_LARGE, (255, 255, 0, 255), OUTLINE_W_LARGE, OUTLINE_COLOR))
                # 法师塔
                if ctype // 100 == 400:
                    texts.append(((x, y), get_name(ctype), FONT_SIZE_SMALL, (210, 255, 200, 255), OUTLINE_W_SMALL, OUTLINE_COLOR))
                # 马车
                if ctype // 10 in (4500, 4501):
                    icons.append(((x, y), CARRIAGE_ICON))
                # POI
                if ctype // 1000 in (30, 32, 34, 38):
                    y += scale_size(15)
                    texts.append(((x, y), get_name(ctype), FONT_SIZE_SMALL, (200, 220, 150, 255), OUTLINE_W_SMALL, OUTLINE_COLOR))
                # 特殊事件（癫火塔除外）
                if ctype // 1000 in (20, 21):
                    icons.append(((x, y), EVENT_ICON))
                    y += scale_size(15)
                    texts.append(((x, y), get_event_text(pattern), FONT_SIZE_SMALL, (255, 200, 200, 255), OUTLINE_W_SMALL, OUTLINE_COLOR))
                

            # 宝藏
            treasure_id = pattern.treasure * 10 + pattern.earth_shifting
            treasure = open_with_draw_size(f"treasures/treasure_{treasure_id}.png", (800, 800))
            icons.append((scale_size((375, 375)), treasure))

            # 癫火塔
            if pattern.event_value == 3080:
                frenzy = open_with_draw_size(f"frenzy/Frenzy_{pattern.evpat_flag}.png", (800, 800))
                icons.append((scale_size((375, 375)), frenzy))

            # 腐败庇佑
            if pos := ROTREW_POS.get(pattern.rot_rew):
                icons.append((pos, ROTREW_ICON))
                texts.append(((pos[0], pos[1] + scale_size(20)), "庇佑", FONT_SIZE_SMALL, (255, 200, 200, 255), OUTLINE_W_SMALL, OUTLINE_COLOR))

            # 说明文本
            text = f"#{pattern.id}    {get_name(pattern.nightlord + 100000)}"
            if event_text := get_event_text(pattern):
                text += f"    特殊事件: {event_text}"
            texts.append((scale_size((20, 10)), text, scale_size(24), (255, 255, 255, 255), scale_size(3), OUTLINE_COLOR, 'lt'))

        else:
            text = f"大空洞：暂无该地图数据，显示可能的Boss与水晶点位"
            texts.append((scale_size((20, 10)), text, scale_size(24), (255, 255, 255, 255), scale_size(3), OUTLINE_COLOR, 'lt'))
            hollow = open_with_draw_size("icons/hollow.png", (800, 800))
            icons.append((scale_size((375, 375)), hollow))

        for icon in icons:  draw_icon(img, *icon)
        for text in texts:  draw_text(img, *text)

        info(f"Draw overlay image size: {draw_size} time cost: {time.time() - t:.4f}s")

        # 保存结果用于调试
        img.convert('RGB').save(get_appdata_path(f"map_overlay_result.jpg"))

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
            pattern, score = self._match_map_pattern(img, param.earth_shifting)
            ret.pattern = pattern
            ret.pattern_score = score

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
            ret.overlay_image = self._draw_overlay_image(pattern, draw_size)
        
        return ret


