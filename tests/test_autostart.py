"""登录后默认自启，面板里可关；关掉后下次启动仍关。"""

from pathlib import Path

from comtee.autostart import AutoStart, PreferredAutoStart
from comtee.persist import UserSettings


def test_自启默认开并可关掉() -> None:
    """开关只动注入的启动项，不碰真注册表。"""
    slots: dict[str, str] = {}
    start = AutoStart(slots, name="串通", command="python -m comtee")
    start.enable_default()
    assert start.is_enabled() is True
    start.set_enabled(False)
    assert start.is_enabled() is False
    assert "串通" not in slots
    start.set_enabled(True)
    assert slots["串通"] == "python -m comtee"


def test_关掉自启后下次启动不会再打开(tmp_path: Path) -> None:
    """偏好写盘；没有 Run 键也不要当成「尚未配置」再打开。"""
    settings = UserSettings(tmp_path / "settings.json")
    first = PreferredAutoStart(
        AutoStart({}, name="串通", command="python -m comtee"),
        settings,
    )
    first.apply_on_launch()
    assert first.is_enabled() is True
    first.set_enabled(False)

    second = PreferredAutoStart(
        AutoStart({}, name="串通", command="python -m comtee"),
        settings,
    )
    second.apply_on_launch()
    assert second.is_enabled() is False
