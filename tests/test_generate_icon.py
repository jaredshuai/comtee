"""安装包图标要能写成 Windows ICO。"""

from pathlib import Path

from PIL import Image

from comtee.branding import write_icon


def test_图标写成多尺寸ico(tmp_path: Path) -> None:
    """给 Nuitka / Inno 的图标不能只剩 16 像素一档。"""
    path = write_icon(tmp_path / "comtee.ico")
    assert path.is_file()
    assert path.stat().st_size > 1000
    with Image.open(path) as image:
        assert image.format == "ICO"
        assert image.size[0] >= 16
