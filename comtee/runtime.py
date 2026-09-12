"""分辨源码运行和 Nuitka 安装包，决定登录自启命令。"""

from __future__ import annotations

import sys


def is_compiled() -> bool:
    """源码运行则否；编进 exe 后为是。"""
    return bool(getattr(sys, "frozen", False) or globals().get("__compiled__"))


def launch_command(
    executable: str | None = None, *, compiled: bool | None = None
) -> str:
    """登录自启应执行的命令。

    源码带 ``-m comtee``；安装包的 ``sys.executable`` 已是 ``comtee.exe``。
    """
    exe = sys.executable if executable is None else executable
    packed = is_compiled() if compiled is None else compiled
    quoted = f'"{exe}"'
    if packed:
        return quoted
    return f"{quoted} -m comtee"
