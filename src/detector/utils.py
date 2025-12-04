import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from mss.base import MSSBase

from src.common import get_data_path
from src.logger import warning, debug


def hls_to_rgb(hls: tuple[int, int, int]) -> tuple[int, int, int]:
    img = np.uint8([[hls]]) 
    img = cv2.cvtColor(img, cv2.COLOR_HLS2RGB)
    return tuple(int(c) for c in img[0][0])

def normalize_image(img: Image.Image) -> Image.Image:
    """
    对图像进行归一化处理
    在HDR模式下，Windows截图API可能返回不同亮度范围的数据，
    导致颜色不一致，影响模板匹配。
    
    这个函数通过归一化将图像的亮度和对比度标准化，
    使用直方图均衡化和对比度拉伸来提高匹配准确性。
    适用于：地图识别等需要增强局部对比度的场景
    """
    # 将PIL图像转换为numpy数组
    img_array = np.array(img)
    
    # 转换到LAB色彩空间，只对亮度通道进行归一化
    lab = cv2.cvtColor(img_array, cv2.COLOR_RGB2LAB)
    l, a, b = cv2.split(lab)
    
    # 对L通道进行CLAHE (对比度受限的自适应直方图均衡化)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_normalized = clahe.apply(l)
    
    # 合并通道
    lab_normalized = cv2.merge([l_normalized, a, b])
    
    # 转换回RGB
    img_normalized = cv2.cvtColor(lab_normalized, cv2.COLOR_LAB2RGB)
    
    return Image.fromarray(img_normalized)

def convert_hdr_to_sdr(img: Image.Image) -> Image.Image:
    """
    将HDR色彩空间的图像转换为SDR色彩空间
    在HDR模式下，Windows截图API可能返回HDR色彩空间的数据，
    导致颜色过亮或不正确，影响模板匹配。
    
    这个函数通过色调映射（tone mapping）将HDR图像转换为SDR图像。
    使用简单的gamma校正和亮度调整来实现基本的色调映射。
    适用于：缩圈倒计时检测等需要保持颜色准确性的场景
    """
    # 将PIL图像转换为numpy数组
    img_array = np.array(img, dtype=np.float32) / 255.0
    
    # 应用gamma校正 (通常HDR使用更高的gamma值)
    # 使用2.2作为标准SDR gamma值
    gamma = 2.2
    img_array = np.power(img_array, 1.0 / gamma)
    
    # 限制亮度范围，避免过曝
    # HDR内容可能包含超过1.0的亮度值
    img_array = np.clip(img_array, 0.0, 1.0)
    
    # 转换回uint8
    img_array = (img_array * 255).astype(np.uint8)
    
    return Image.fromarray(img_array)
    
def get_size_by_height(size: tuple[int], target_height: int) -> tuple[int]:
    width, height = size
    aspect_ratio = width / height
    target_width = int(target_height * aspect_ratio)
    return (target_width, target_height)

def get_size_by_width(size: tuple[int], target_width: int) -> tuple[int]:
    width, height = size
    aspect_ratio = width / height
    target_height = int(target_width / aspect_ratio)
    return (target_width, target_height)

def resize_by_height_keep_aspect_ratio(image: Image.Image, target_height: int) -> Image.Image:
    target_size = get_size_by_height(image.size, target_height)
    return image.resize(target_size, Image.Resampling.LANCZOS)

def resize_by_width_keep_aspect_ratio(image: Image.Image, target_width: int) -> Image.Image:
    target_size = get_size_by_width(image.size, target_width)
    return image.resize(target_size, Image.Resampling.LANCZOS)

def resize_by_scale(image: Image.Image, scale: float) -> Image.Image:
    target_size = (int(image.size[0] * scale), int(image.size[1] * scale))
    return image.resize(target_size, Image.Resampling.LANCZOS)

def paste_cv2(img1: np.ndarray, img2: np.ndarray, pos: tuple[int, int]):
    x, y = pos
    h, w = img2.shape[0], img2.shape[1]
    img1[y:y+h, x:x+w] = img2

def grab_region(sct: MSSBase, region: tuple[int], processing: str = 'none') -> Image.Image:
    """
    截取屏幕区域并可选地进行图像处理
    
    Args:
        sct: 截图对象
        region: 截图区域 (x, y, w, h)
        processing: 图像处理方式
            - 'none': 不进行任何处理（默认）
            - 'normalize': 使用归一化处理（适用于地图识别）
            - 'hdr_to_sdr': 使用HDR到SDR转换（适用于缩圈倒计时）
    """
    from src.config import Config
    
    x, y, w, h = region
    
    # 首先检查坐标是否已经是绝对坐标（包含屏幕偏移）
    # 如果坐标在任何屏幕的范围内，直接使用
    for monitor in sct.monitors[1:]:  # 跳过 monitors[0] (所有屏幕的汇总)
        if (monitor["left"] <= x < monitor["left"] + monitor["width"] and
                monitor["top"] <= y < monitor["top"] + monitor["height"]):
            # 坐标已经是绝对坐标，直接截图
            screenshot = sct.grab({
                "left": x,
                "top": y,
                "width": w,
                "height": h
            })
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra,
                                  "raw", "BGRX")
            
            # 根据processing参数进行图像处理
            if processing == 'normalize':
                debug(f"Applying image normalization for region {region}")
                img = normalize_image(img)
            elif processing == 'hdr_to_sdr':
                debug(f"Applying HDR to SDR conversion for region {region}")
                img = convert_hdr_to_sdr(img)
            # processing == 'none' 时不做任何处理
            
            return img
    
    # 如果没有找到匹配的屏幕，可能是相对坐标，尝试转换为绝对坐标
    # 默认使用主屏幕偏移（保持向后兼容）
    main_screen = sct.monitors[1]
    main_screen_offset = (main_screen["left"], main_screen["top"])
    absolute_region = (
        x + main_screen_offset[0],
        y + main_screen_offset[1],
        w,
        h,
    )
    
    # 验证转换后的坐标是否有效
    abs_x, abs_y, abs_w, abs_h = absolute_region
    for monitor in sct.monitors[1:]:
        if (monitor["left"] <= abs_x < monitor["left"] + monitor["width"] and
                monitor["top"] <= abs_y < monitor["top"] + monitor["height"]):
            screenshot = sct.grab({
                "left": abs_x,
                "top": abs_y,
                "width": abs_w,
                "height": abs_h
            })
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra,
                                  "raw", "BGRX")
            
            # 根据processing参数进行图像处理
            if processing == 'normalize':
                debug(f"Applying image normalization for region {region}")
                img = normalize_image(img)
            elif processing == 'hdr_to_sdr':
                debug(f"Applying HDR to SDR conversion for region {region}")
                img = convert_hdr_to_sdr(img)
            
            return img
    
    # 如果仍然找不到有效屏幕，使用原始逻辑作为最后的fallback
    warning(f"Region {region} could not be mapped to any screen. "
            f"Using fallback method.")
    screenshot = sct.grab({
        "left": abs_x,
        "top": abs_y,
        "width": abs_w,
        "height": abs_h
    })
    img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
    
    # 根据processing参数进行图像处理
    if processing == 'normalize':
        debug(f"Applying image normalization for region {region}")
        img = normalize_image(img)
    elif processing == 'hdr_to_sdr':
        debug(f"Applying HDR to SDR conversion for region {region}")
        img = convert_hdr_to_sdr(img)
    
    return img


DEFAULT_FONT_PATH = get_data_path("fonts/SourceHanSansSC-Normal.otf")

font_cache = {}


def get_font(size: int, path: str=DEFAULT_FONT_PATH) -> ImageFont.FreeTypeFont:
    key = f"{path}-{size}"
    if key not in font_cache:
        font_cache[key] = ImageFont.truetype(path, size)
    return font_cache[key]


def get_text_size(font: ImageFont.FreeTypeFont, text: str) -> tuple[int, int]:
    return font.getbbox(text)[2:4]


def draw_icon(img: Image.Image, pos: tuple[int, int], icon: Image.Image, size: tuple[int, int] | None = None):
    if size is None:
        size = icon.size
    icon = icon.resize(size, resample=Image.Resampling.BICUBIC)
    img.alpha_composite(icon, (pos[0] - size[0] // 2, pos[1] - size[1] // 2))


def draw_text(img: Image.Image, pos: tuple[int, int], text: str, size: int,
              color: tuple[int, int, int, int],
              outline_width: int = 0,
              outline_color: tuple[int, int, int, int] = (0, 0, 0, 255),
              align='c'):
    assert align in ('lb', 'c', 'lt')
    if text is None: text = "null"
    draw = ImageDraw.Draw(img)
    font = get_font(size)
    text_size = get_text_size(font, text)
    if align == 'lb':
        pos = (pos[0] + text_size[0] // 2, pos[1] - text_size[1] // 2)
    elif align == 'lt':
        pos = (pos[0] + text_size[0] // 2, pos[1] + text_size[1] // 2)
    if outline_width > 0:
        for dx in range(-outline_width, outline_width+1):
            for dy in range(-outline_width, outline_width+1):
                if dx*dx + dy*dy <= outline_width * outline_width:
                    draw.text((pos[0] - text_size[0] // 2 + dx,
                              pos[1] - text_size[1] // 2 + dy), text,
                              font=font, fill=outline_color)
    draw.text((pos[0] - text_size[0] // 2, pos[1] - text_size[1] // 2),
              text, font=font, fill=color)


def match_template(
    image: np.ndarray, 
    template: np.ndarray, 
    scales: tuple[float, float, int], 
    mask: np.ndarray=None
) -> tuple[tuple[int, int, int, float] | None, float]:
    best_match = None
    best_val = float('inf')
    for scale in np.linspace(scales[0], scales[1], num=scales[2], endpoint=True):
        resized_template = cv2.resize(template, (int(template.shape[1] * scale), int(template.shape[0] * scale)))
        if resized_template.shape[0] > image.shape[0] or resized_template.shape[1] > image.shape[1]:
            continue
        if mask is not None:
            mask = cv2.resize(mask, (resized_template.shape[1], resized_template.shape[0]))
        result = cv2.matchTemplate(image, resized_template, cv2.TM_SQDIFF_NORMED, mask)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        if min_val < best_val:
            best_val = min_val
            best_match = (min_loc, resized_template.shape[1], resized_template.shape[0], scale)
    return best_match, best_val