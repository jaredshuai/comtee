"""NiceGUI 原生窗口：关面板只隐藏，托盘退出才放口。"""

from typing import Any, cast

from nicegui.native import native_mode

_SPAWN_PATCHED = False
_REAL_OPEN = native_mode._open_window


def attach_hide_on_close(window: Any) -> None:
    """关掉窗口时隐藏并否决关闭，进程继续占口。"""

    def closing() -> bool:
        """隐藏窗口并取消关闭。"""
        window.hide()
        return False

    window.events.closing += closing


def patch_bind() -> None:
    """在窗口子进程里给 NiceGUI 补上 closing 拦截。"""
    original = native_mode._bind_pywebview_events

    def bind(window: Any, event_sender: Any) -> None:
        """先走 NiceGUI 原绑定，再拦截 closing。"""
        original(window, event_sender)
        attach_hide_on_close(window)

    native_mode._bind_pywebview_events = cast(Any, bind)


def child_open_window(*args: Any, **kwargs: Any) -> None:
    """窗口子进程入口：先拦截关窗，再打开 NiceGUI 窗口。"""
    patch_bind()
    _REAL_OPEN(*args, **kwargs)


def install_hide_on_close() -> None:
    """父进程：把窗口 Process 的 target 换成 child_open_window。

    ``python -m comtee`` 时 CPython spawn 不会重跑入口为 ``__mp_main__``。
    pickle 按函数自身的模块名还原，所以必须让 target 就是本模块的函数。
    """
    global _SPAWN_PATCHED
    if _SPAWN_PATCHED:
        return
    native_mode._open_window = cast(Any, child_open_window)
    _SPAWN_PATCHED = True
