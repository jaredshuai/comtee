"""串通管理面板：编排线路、看占用冲突和谁连着，不看字节流。"""

from collections.abc import Callable

from nicegui import ui

from comtee.autostart import AutoStart, PreferredAutoStart
from comtee.hub import ArrangementRejected, Comtee, SerialParams, UsbIdentity

_TITLE = "串通"


def build_panel(
    hub: Comtee,
    list_paths: Callable[[], dict[UsbIdentity, str]],
    autostart: AutoStart | PreferredAutoStart,
) -> None:
    """画出面板。关窗不等于退出，由调用方接托盘。"""
    ui.page_title(_TITLE)
    ui.label(_TITLE).classes("text-h4")
    ui.label("编排线路、看占用和谁连着。这里不看设备字节流。").classes("text-caption")
    autostart_switch = ui.switch(
        "登录后自启",
        value=autostart.is_enabled(),
        on_change=lambda e: autostart.set_enabled(bool(e.value)),
    )

    entry = ui.number("人端入口", value=2222, format="%.0f")
    device_select = ui.select(options={}, label="设备（USB 身份）").classes("w-full")
    baud = ui.select(
        [9600, 19200, 38400, 57600, 115200],
        value=9600,
        label="波特率",
    )
    decode = ui.select(["gbk", "utf-8"], value="gbk", label="解码")
    notice = ui.label("")

    def refresh_devices() -> None:
        """刷新现场 USB 设备下拉框，展示此刻路径但不把它当身份。"""
        paths = list_paths()
        device_select.options = {
            _key(identity): f"{_key(identity)}  {path}"
            for identity, path in paths.items()
        }
        device_select.update()

    def create() -> None:
        """创建一条一对一线路。"""
        selected = device_select.value
        if not selected:
            notice.set_text("先选一台设备")
            return
        identity = _parse_key(str(selected))
        port = int(entry.value or 0)
        try:
            hub.create_line(port, identity)
            if int(baud.value or 9600) != 9600 or str(decode.value) != "gbk":
                hub.change_line(
                    port,
                    serial_params=SerialParams(baudrate=int(baud.value or 9600)),
                    decode=str(decode.value),
                )
            notice.set_text("")
        except ArrangementRejected as exc:
            notice.set_text(str(exc))
        redraw_lines()

    def change() -> None:
        """改已有线路的串口参数和解码，不改 USB 身份和人端入口。"""
        port = int(entry.value or 0)
        try:
            hub.change_line(
                port,
                serial_params=SerialParams(baudrate=int(baud.value or 9600)),
                decode=str(decode.value),
            )
            notice.set_text("")
        except KeyError:
            notice.set_text("没有这条线路")
        redraw_lines()

    ui.button("创建线路", on_click=create)
    ui.button("改线路", on_click=change)
    lines_box = ui.column().classes("w-full gap-2")

    def redraw_lines() -> None:
        """刷新线路卡片：状态和谁连着，不画字节。"""
        lines_box.clear()
        paths = list_paths()
        with lines_box:
            if not hub.list_lines():
                ui.label("还没有线路")
                return
            for line in hub.list_lines():
                path = paths.get(line.device, "（此刻没有路径）")
                who = f"人端 {line.human_clients}；Agent {'在' if line.agent_connected else '不在'}"
                with ui.card().classes("w-full"):
                    ui.label(f"入口 {line.human_entry}  →  {_key(line.device)}")
                    ui.label(f"此刻路径 {path}")
                    ui.label(f"状态 {line.hold}")
                    ui.label(f"{line.serial_params.baudrate} {line.decode}")
                    ui.label(who)
                    ui.button(
                        "拆掉", on_click=lambda port=line.human_entry: remove(port)
                    )

    def remove(port: int) -> None:
        """拆掉一条线路并放口。"""
        hub.remove_line(port)
        redraw_lines()

    def tick() -> None:
        """对照现场设备并刷新面板。"""
        hub.refresh()
        refresh_devices()
        redraw_lines()
        autostart_switch.value = autostart.is_enabled()

    refresh_devices()
    redraw_lines()
    ui.timer(1.0, tick)


def _key(identity: UsbIdentity) -> str:
    """下拉框用的身份键，不是 COM 路径。"""
    return f"{identity.vid:04X}:{identity.pid:04X}|{identity.serial}"


def _parse_key(text: str) -> UsbIdentity:
    """从身份键还原 USB 身份。"""
    vid_pid, serial = text.split("|", 1)
    vid_s, pid_s = vid_pid.split(":", 1)
    return UsbIdentity(vid=int(vid_s, 16), pid=int(pid_s, 16), serial=serial)
