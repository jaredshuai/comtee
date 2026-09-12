"""串通窗口与安装包共用的蓝标。"""

from pathlib import Path

from PIL import Image, ImageDraw

_SIZES = (16, 32, 48, 64, 128, 256)
_BLUE = (36, 100, 197, 255)
_WHITE = (255, 255, 255, 255)


def draw_mark(size: int) -> Image.Image:
    """按面板顶栏同样的蓝底白框画出一档尺寸。"""
    image = Image.new("RGBA", (size, size), _BLUE)
    draw = ImageDraw.Draw(image)
    pad = max(2, size * 10 // 64)
    top = max(3, size * 18 // 64)
    bottom = size - max(3, size * 18 // 64)
    width = max(1, size // 16)
    draw.rectangle((pad, top, size - pad, bottom), outline=_WHITE, width=width)
    return image


def write_icon(path: Path) -> Path:
    """写成多尺寸 ICO，供安装包和 exe 版本资源使用。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    largest = draw_mark(_SIZES[-1])
    largest.save(path, format="ICO", sizes=[(size, size) for size in _SIZES])
    return path
