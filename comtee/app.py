"""串通进程：单例、恢复线路、托盘常驻、面板可关可再开。"""

import os
import sys
import threading
from pathlib import Path
from typing import Any, cast

from nicegui import app, native, ui

from comtee.autostart import PreferredAutoStart, windows_autostart
from comtee.hub import Comtee, UsbIdentity
from comtee.native_window import install_hide_on_close
from comtee.panel import build_panel
from comtee.persist import FileArrangementStore, UserSettings
from comtee.singleton import InstanceLock
from comtee.telnet import TelnetEntries
from comtee.usb_serial import UsbSerial, windows_usb_serial

_TITLE = "串通"
_MUTEX = "comtee"


def run() -> None:
    """启动串通；已有一份在跑则退出。"""
    lock = InstanceLock(_MUTEX)
    if not lock.acquire():
        print("串通已在运行。")
        raise SystemExit(1)

    data_dir = Path(os.environ.get("LOCALAPPDATA", ".")) / "comtee"
    adapter: UsbSerial = windows_usb_serial()
    human = TelnetEntries()
    hub = Comtee(
        adapter,
        FileArrangementStore(data_dir / "lines.json"),
        human=human,
    )
    command = f'"{sys.executable}" -m comtee'
    autostart = PreferredAutoStart(
        windows_autostart(command),
        UserSettings(data_dir / "settings.json"),
    )
    autostart.apply_on_launch()
    tray_holder: dict[str, object] = {}

    def list_paths() -> dict[UsbIdentity, str]:
        """现场 USB 身份到此刻 COM 路径。"""
        return adapter.paths()

    def show_panel() -> None:
        """从托盘再打开面板。"""
        window = cast(Any, app.native.main_window)
        if window is not None:
            window.show()
            window.restore()

    def quit_app() -> None:
        """从托盘退出：放口并结束进程。"""
        hub.shutdown()
        lock.release()
        icon = tray_holder.get("icon")
        stop = getattr(icon, "stop", None)
        if callable(stop):
            stop()
        app.shutdown()

    def start_tray() -> None:
        """托盘提示写「串通」。"""
        import pystray
        from PIL import Image, ImageDraw

        image = Image.new("RGB", (64, 64), "#1d4ed8")
        draw = ImageDraw.Draw(image)
        draw.rectangle((10, 18, 54, 46), outline="white", width=4)
        menu = pystray.Menu(
            pystray.MenuItem("打开面板", lambda *_args: show_panel(), default=True),
            pystray.MenuItem("退出", lambda *_args: quit_app()),
        )
        icon = pystray.Icon("comtee", image, _TITLE, menu)
        tray_holder["icon"] = icon
        threading.Thread(target=icon.run, daemon=True).start()

    build_panel(hub, list_paths, autostart)
    app.on_startup(start_tray)
    app.on_shutdown(human.shutdown)
    app.on_shutdown(hub.shutdown)
    install_hide_on_close()
    ui.run(
        native=True,
        reload=False,
        title=_TITLE,
        window_size=(720, 640),
        port=native.find_open_port(),
    )
