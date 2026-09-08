"""关面板窗口只隐藏，不等于退出串通。"""

import pickle
from types import SimpleNamespace
from typing import Any, cast

from nicegui.native import native_mode

from comtee.native_window import (
    attach_hide_on_close,
    child_open_window,
    install_hide_on_close,
    patch_bind,
)


class _FakeEvent:
    """记录挂上的关窗处理。"""

    def __init__(self) -> None:
        self.handlers: list = []

    def __iadd__(self, handler):
        """模拟 pywebview 的 events.closing += handler。"""
        self.handlers.append(handler)
        return self


class _FakeWindow:
    """只观察 hide 与是否允许关闭。"""

    def __init__(self) -> None:
        self.hidden = False
        self.events = SimpleNamespace(closing=_FakeEvent())

    def hide(self) -> None:
        """藏起窗口。"""
        self.hidden = True


def _call_bind(window: object, sender: object) -> None:
    """测试里用假窗口调用当前绑定，不走 pywebview 类型。"""
    bind = cast(Any, native_mode._bind_pywebview_events)
    bind(window, sender)


def test_关窗只隐藏并取消关闭() -> None:
    """关掉面板必须留下进程，所以关闭必须被否决。"""
    window = _FakeWindow()
    attach_hide_on_close(window)

    allowed = window.events.closing.handlers[0]()

    assert window.hidden is True
    assert allowed is False


def test_补丁会先走原绑定再拦截关窗(monkeypatch) -> None:
    """子进程里必须包住 NiceGUI 的 _bind_pywebview_events。"""
    called: list[str] = []

    def fake_bind(window, event_sender) -> None:
        """确认原绑定仍被调用。"""
        called.append("bind")

    monkeypatch.setattr(native_mode, "_bind_pywebview_events", fake_bind)
    patch_bind()
    window = _FakeWindow()
    _call_bind(window, None)
    allowed = window.events.closing.handlers[0]()

    assert called == ["bind"]
    assert window.hidden is True
    assert allowed is False


def test_窗口子进程入口先拦截再打开(monkeypatch) -> None:
    """Process 的 target 必须是本模块函数，这样 spawn 才会导入串通。"""
    order: list[str] = []

    def fake_open(*args, **kwargs) -> None:
        """记录打开窗口发生在补丁之后。"""
        order.append("open")

    monkeypatch.setattr("comtee.native_window._REAL_OPEN", fake_open)
    monkeypatch.setattr(
        native_mode,
        "_bind_pywebview_events",
        lambda window, sender: order.append("original-bind"),
    )
    child_open_window()
    window = _FakeWindow()
    _call_bind(window, None)

    assert order == ["open", "original-bind"]
    assert window.events.closing.handlers[0]() is False
    assert window.hidden is True


def test_父进程替换后窗口入口能被pickle还原() -> None:
    """spawn 按函数自身的模块名还原，不能依赖 native_mode 里的原名。"""
    install_hide_on_close()
    restored = pickle.loads(pickle.dumps(native_mode._open_window))
    assert restored is child_open_window
