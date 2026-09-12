"""串通管理面板：B 布局编排线路，不看字节流。"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from nicegui import ui

from comtee.autostart import AutoStart, PreferredAutoStart
from comtee.hub import (
    ArrangementRejected,
    Comtee,
    HumanEntryOccupied,
    LineHold,
    LineStatus,
    SerialApplyFailed,
    UsbIdentity,
)
from comtee.line_edit import (
    ALLOWED_DATA_BITS,
    ALLOWED_STOP_BITS,
    BAUD_PRESETS,
    CHARSET_LABELS,
    FLOW_LABELS,
    PARITY_LABELS,
    DeviceChoice,
    Draft,
    LineView,
    agent_share_text,
    charset_label,
    create_device_choices,
    create_port_conflict_error,
    created_connection,
    default_create_draft,
    draft_serial_params,
    failure_notices,
    format_bytes,
    format_last_rx,
    format_preview,
    identity_key,
    impact_text,
    line_health,
    listen_address,
    parse_identity_key,
    recovery_notice,
    serial_format,
    status_to_view,
    suggest_port,
    validate_draft,
)
from comtee.panel_style import PANEL_CSS

_TITLE = "串通"
_MARK_SVG = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M6 5v7h12V5M12 12v7"/><circle cx="6" cy="4" r="1"/>'
    '<circle cx="18" cy="4" r="1"/><circle cx="12" cy="20" r="1"/></svg>'
)
_ICON = {
    "close": '<path d="m6 6 12 12M6 18 18 6"/>',
    "left": '<path d="m14 5-7 7 7 7"/>',
    "right": '<path d="m10 5 7 7-7 7"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 4H6a2 2 0 0 0-2 2v10"/>',
    "gear": '<path d="M4 7h16M4 17h16M8 4v6M16 14v6"/>',
}


def build_panel(
    hub: Comtee,
    list_paths: Callable[[], dict[UsbIdentity, str]],
    autostart: AutoStart | PreferredAutoStart,
) -> None:
    """画出 B 布局面板。关窗不等于退出，由调用方接托盘。"""
    Panel(hub, list_paths, autostart).build()


class Panel:
    """左右分栏的线路编排界面；刷新时更新已有控件，不整页拆掉。"""

    def __init__(
        self,
        hub: Comtee,
        list_paths: Callable[[], dict[UsbIdentity, str]],
        autostart: AutoStart | PreferredAutoStart,
    ) -> None:
        """注入串通、现场枚举和自启偏好。"""
        self._hub = hub
        self._list_paths = list_paths
        self._autostart = autostart
        self._selected: int | None = None
        self._collapsed = False
        self._dialog_open = False
        self._device_open = False
        self._notice: dict[str, Any] | None = None
        self._rendered_entries: list[int] = []
        self._content: Any = None
        self._split: Any = None
        self._detail: Any = None
        self._rail_buttons: dict[int, Any] = {}
        self._labels: dict[str, Any] = {}
        self._editor: Any = None
        self._confirm: Any = None
        self._form: dict[str, Any] = {}
        self._editing_entry: int | None = None
        self._notice_sig: tuple[object, ...] | None = None
        self._views: dict[int, LineView] = {}

    def build(self) -> None:
        """画出外壳、对话框和定时刷新。"""
        ui.page_title(_TITLE)
        ui.add_css(PANEL_CSS)
        with ui.element("div").classes("comtee-shell"):
            self._header()
            self._content = ui.element("div").classes("comtee-content")
        self._editor = ui.dialog()
        self._confirm = ui.dialog()
        self._editor.on("hide", lambda: self._set_dialog_open(False))
        self._confirm.on("hide", lambda: self._set_dialog_open(False))
        self._render_content()
        ui.timer(1.0, self._tick)

    def _set_dialog_open(self, open_: bool) -> None:
        """对话框开着时，定时器不得拆掉正在编辑的输入。"""
        self._dialog_open = open_

    def _icon_button(
        self,
        kind: str,
        on_click: Callable[[], None],
        tooltip: str,
    ) -> Any:
        """画出带 SVG 的图标按钮，保证点击区域盖住图形。"""
        btn = (
            ui.button(on_click=on_click, color=None)
            .props("flat round unelevated")
            .classes("icon-button quiet")
        )
        if tooltip:
            btn.tooltip(tooltip)
        with btn:
            ui.html(
                f'<svg class="icon" viewBox="0 0 24 24">{_ICON[kind]}</svg>',
                sanitize=False,
            )
        return btn

    def _header(self) -> None:
        """顶栏：产品名、新建线路和应用设置。"""
        with ui.element("header").classes("app-header"):
            with ui.element("div").classes("brand"):
                ui.html(
                    f'<div class="mark" aria-hidden="true">{_MARK_SVG}</div>',
                    sanitize=False,
                )
                with ui.element("div"):
                    ui.html('<h1 class="brand-title">串通</h1>', sanitize=False)
                    ui.label("线路常驻，人和 Agent 随时接入").classes("subtitle")
            with ui.element("div").classes("header-actions"):
                ui.button(
                    "＋ 新建线路",
                    on_click=lambda: self._open_editor(None),
                ).props("no-caps unelevated").classes("primary")
                self._icon_button("gear", self._open_settings, "应用设置")

    def _tick(self) -> None:
        """对照现场；对话框打开时只更新串通状态，不重建面板。"""
        self._hub.refresh()
        editor_open = bool(self._editor.value) if self._editor is not None else False
        confirm_open = bool(self._confirm.value) if self._confirm is not None else False
        self._dialog_open = editor_open or confirm_open
        if self._dialog_open:
            return
        lines = self._hub.list_lines()
        self._track_recovery(lines)
        entries = [line.human_entry for line in lines]
        if entries != self._rendered_entries or (
            self._selected is not None and self._selected not in entries and entries
        ):
            self._render_content()
            return
        if not lines:
            return
        self._patch(lines)

    def _render_content(self) -> None:
        """线路集合变化时重画分栏；保留选中项和折叠状态。"""
        if self._content is None:
            return
        lines = list(self._hub.list_lines())
        self._rendered_entries = [line.human_entry for line in lines]
        if self._selected not in self._rendered_entries:
            self._selected = (
                self._rendered_entries[0] if self._rendered_entries else None
            )
        self._rail_buttons = {}
        self._labels = {}
        self._content.clear()
        with self._content:
            if not lines:
                self._render_empty()
                return
            selected = self._line(lines)
            collapsed = " collapsed" if self._collapsed else ""
            self._split = ui.element("div").classes(f"split{collapsed}")
            with self._split:
                self._render_rail(lines, selected)
                self._detail = ui.element("section").classes("detail")
                with self._detail:
                    self._fill_detail(selected)
            self._notice_sig = self._status_sig(selected)
            self._seed_views(lines)

    def _render_empty(self) -> None:
        """还没有线路时的接入说明。"""
        with ui.element("section").classes("empty"):
            ui.html("<h2>接入你的第一条线路</h2>", sanitize=False)
            ui.label(
                "插上 USB 转接器，为设备留一个人端入口。人和 Agent 就能从同一条线路接入。"
            )
            ui.button("＋ 新建线路", on_click=lambda: self._open_editor(None)).props(
                "no-caps unelevated"
            ).classes("primary")

    def _render_rail(self, lines: list[LineStatus], selected: LineStatus) -> None:
        """左侧线路列表；折叠后仍显示端口和状态点。"""
        with ui.element("aside").classes("rail"):
            with ui.element("div").classes("railhead"):
                count = len(lines)
                ui.html(
                    f'<h2 class="rail-title-text">我的线路<span class="count">{count}</span></h2>',
                    sanitize=False,
                )
                self._icon_button(
                    "right" if self._collapsed else "left",
                    self._toggle_rail,
                    "展开线路栏" if self._collapsed else "折叠线路栏",
                )
            for line in lines:
                self._rail_item(line, line.human_entry == selected.human_entry)

    def _rail_item(self, line: LineStatus, active: bool) -> None:
        """一条线路的列表项：端口最醒目。"""
        view = status_to_view(line, self._path_of(line))
        health = line_health(view)
        port = line.human_entry

        def choose() -> None:
            """切换详情，不丢掉折叠状态。"""
            self._selected = port
            self._notice = (
                None
                if self._notice and self._notice.get("entry") != port
                else self._notice
            )
            self._render_content()

        btn = (
            ui.button(on_click=choose, color=None)
            .props("flat no-caps unelevated")
            .classes("railitem" + (" active" if active else ""))
            .tooltip(f"{port} · {line.name or '未命名线路'} · {health.badge}")
        )
        with btn, ui.element("div").classes("rail-line"):
            with ui.element("div").classes("rail-title"):
                ui.label(str(port)).classes("mono")
                ui.label(line.name or "未命名线路").classes("rail-alias")
            state = ui.label(health.badge).classes(
                f"rail-state rail-state-text {health.badge_class}"
            )
            device = ui.label(health.device).classes(
                f"rail-meta rail-device {health.device_class}"
            )
            human = ui.label(health.human).classes(
                f"rail-meta rail-human {health.human_class}"
            )
            clients = ui.label(health.clients).classes("rail-meta rail-clients")
            self._labels[f"rail-state-{port}"] = state
            self._labels[f"rail-device-{port}"] = device
            self._labels[f"rail-human-{port}"] = human
            self._labels[f"rail-clients-{port}"] = clients
        self._rail_buttons[port] = btn

    def _toggle_rail(self) -> None:
        """折叠或展开左栏；选中项保持。"""
        self._collapsed = not self._collapsed
        self._render_content()

    def _fill_detail(self, line: LineStatus) -> None:
        """右侧详情：端口、分离的链路状态、完整串口格式。"""
        view = status_to_view(line, self._path_of(line))
        health = line_health(view)
        params = line.serial_params
        missing = line.hold == LineHold.WAITING
        with ui.element("div").classes("detail-top"):
            with ui.element("div"):
                ui.label("人端入口").classes("eyebrow")
                with ui.element("div").classes("port mono"):
                    self._labels["port"] = ui.label(str(line.human_entry)).style(
                        "display:inline"
                    )
                    self._labels["alias"] = (
                        ui.label(line.name or "")
                        .classes("line-alias")
                        .style("display:inline")
                    )
            self._labels["badge"] = ui.label(health.badge).classes(
                f"badge {health.badge_class}"
            )
        with ui.element("div").classes("endpoint"):
            self._labels["address"] = ui.label(
                listen_address(line.human_entry)
            ).classes("mono")
            ui.button(
                "复制地址",
                on_click=lambda: self._copy(
                    listen_address(line.human_entry), "人端地址已复制"
                ),
                color=None,
            ).props("flat no-caps").classes("quiet link-button")
            ui.button(
                "给 Agent 的说明",
                on_click=lambda: self._open_agent_help(line),
                color=None,
            ).props("flat no-caps").classes("quiet link-button")
        with ui.element("div").classes("link-status"):
            self._labels["rw"] = ui.label(health.rw_label).classes(
                f"status-item {self._rw_class(health.writable, line.human_listening)}"
            )
            self._labels["human"] = ui.label(health.human).classes(
                f"status-item {health.human_class}"
            )
            self._labels["device"] = ui.label(health.device).classes(
                f"status-item {health.device_class}"
            )
            self._labels["clients-status"] = ui.label(health.clients).classes(
                "status-item"
            )
        self._labels["notices"] = ui.element("div")
        with self._labels["notices"]:
            self._fill_notices(line, view)
        with ui.element("div").classes("sectionhead"):
            ui.label("连接参数").classes("section-title")
            ui.button(
                "线路设置 ›",
                on_click=lambda port=line.human_entry: self._open_editor(port),
                color=None,
            ).props("flat no-caps").classes("quiet link-button")
        with ui.element("div").classes("param-grid"):
            self._param("波特率", str(params.baudrate), "波特 / 秒", "baud")
            self._param(
                "串口格式",
                serial_format(params),
                f"{params.data_bits} 数据位 · {PARITY_LABELS.get(params.parity, params.parity)} · {params.stop_bits} 停止位",
                "format",
            )
            self._param(
                "Agent 字符集",
                charset_label(line.decode),
                "文本接收与发送",
                "charset",
            )
        flow_cls = (
            "flow-control configured"
            if params.flow_control != "none"
            else "flow-control"
        )
        with ui.element("div").classes(flow_cls):
            ui.label("流控")
            self._labels["flow"] = ui.label(
                FLOW_LABELS.get(params.flow_control, params.flow_control)
            ).classes("flow-value")
        with ui.element("div").classes("clients"):
            ui.label("谁连着").classes("section-title")
            with ui.element("div").classes("client-values"):
                self._labels["humans"] = ui.label(f"人端 {line.human_clients}")
                agent_cls = "presence" if line.agent_connected else "muted"
                self._labels["agent"] = ui.label(
                    f"Agent {'已连接' if line.agent_connected else '未连接'}"
                ).classes(agent_cls)
        with ui.element("div").classes("activity"):
            self._activity("设备接收", format_bytes(line.rx_bytes), "rx")
            self._activity("写入设备", format_bytes(line.tx_bytes), "tx")
            self._activity(
                "最近收到设备数据",
                format_last_rx(line.last_rx_at, missing=missing),
                "last",
            )
        note = (
            "本次运行累计；写入设备不代表设备已执行指令。"
            if line.last_rx_at
            else "尚无设备输出；没有输出本身不能证明参数错误。"
        )
        self._labels["note"] = ui.label(note).classes("activity-note")
        with ui.expansion(
            "设备信息",
            value=self._device_open,
            on_value_change=lambda e: setattr(self, "_device_open", bool(e.value)),
        ).classes("device-info"):
            path_text = "设备未接入" if missing else f"当前 {view.device_path}"
            self._labels["devpath"] = ui.label(path_text)
            ui.label(f"USB 身份  {view.device_key}").classes("mono")
            ui.label(
                "线路按 USB 身份识别转接器，COM 路径可能变化。线路名称由你填写；"
                "转接器换接到另一台机器后，请自行核对名称。"
            ).classes("tiny muted")
        with ui.element("div").classes("detail-bottom"):
            ui.label("关掉窗口后，串通仍在托盘运行。")
            ui.button(
                "拆掉线路",
                on_click=lambda port=line.human_entry: self._confirm_remove(port),
                color=None,
            ).props("flat no-caps").classes("quiet danger")

    def _param(self, title: str, value: str, note: str, key: str) -> None:
        """连接参数三格中的一格。"""
        with ui.element("div").classes("param"):
            ui.html(f"<small>{title}</small>", sanitize=False)
            self._labels[key] = ui.label(value).classes("param-value mono")
            self._labels[f"{key}-note"] = ui.label(note).classes("param-note")

    def _activity(self, title: str, value: str, key: str) -> None:
        """收发计数中的一格。"""
        with ui.element("div"):
            ui.html(f"<small>{title}</small>", sanitize=False)
            self._labels[key] = ui.label(value).classes("activity-value mono")

    def _fill_notices(self, line: LineStatus, view: LineView) -> None:
        """保存结果、恢复反馈，以及每个失败状态的原因和下一步。"""
        notice = self._notice
        if notice and notice.get("entry") == line.human_entry:
            copies = created_connection(view)
            with ui.element("section").classes("notice success"):
                ui.label(str(notice["title"])).classes("notice-title")
                ui.label(str(notice["message"]))
                if notice.get("reconnect"):
                    ui.label(
                        f"请将 Telnet 书签更新为 {listen_address(line.human_entry)}；"
                        f"Agent 后续请指名 {line.human_entry}。"
                    )
                if notice.get("copy_connection"):
                    ui.label(copies.address).classes("mono")
                    with ui.element("div").classes("notice-actions"):
                        ui.button(
                            copies.address_label,
                            on_click=lambda text=copies.address: self._copy(
                                text, "人端地址已复制"
                            ),
                            color=None,
                        ).props("flat no-caps").classes("quiet link-button")
                        ui.button(
                            copies.agent_label,
                            on_click=lambda text=copies.agent_text: self._copy(
                                text, "Agent/MCP 说明已复制"
                            ),
                            color=None,
                        ).props("flat no-caps").classes("quiet link-button")
                ui.button("关闭", on_click=self._dismiss_notice).props(
                    "flat no-caps"
                ).classes("quiet")
        for item in failure_notices(view):
            cls = "notice error" if item.severity == "error" else "notice"
            with ui.element("section").classes(cls):
                ui.label(item.title).classes("notice-title")
                ui.label(item.reason)
                ui.label(item.next_action)
                with ui.element("div").classes("notice-actions"):
                    if item.action:
                        ui.button(
                            item.action_label,
                            on_click=lambda port=line.human_entry: self._retry(port),
                        ).props("no-caps unelevated")
                    if item.kind == "port":
                        ui.button(
                            "更换入口端口",
                            on_click=lambda port=line.human_entry: self._open_editor(
                                port
                            ),
                        ).props("no-caps unelevated")

    def _dismiss_notice(self) -> None:
        """关掉保存成功或恢复反馈。"""
        self._notice = None
        self._render_content()

    def _patch(self, lines: Sequence[LineStatus]) -> None:
        """一秒一次更新状态文字，不拆掉详情和折叠。"""
        selected = self._line(lines)
        view = status_to_view(selected, self._path_of(selected))
        health = line_health(view)
        params = selected.serial_params
        missing = selected.hold == LineHold.WAITING
        self._set("port", str(selected.human_entry))
        self._set("alias", selected.name or "")
        if "badge" in self._labels:
            self._labels["badge"].set_text(health.badge)
            self._labels["badge"].classes(replace=f"badge {health.badge_class}".strip())
        self._set("address", listen_address(selected.human_entry))
        self._set("rw", health.rw_label)
        if "rw" in self._labels:
            self._labels["rw"].classes(
                replace=(
                    f"status-item {self._rw_class(health.writable, selected.human_listening)}"
                ).strip()
            )
        self._set("human", health.human)
        if "human" in self._labels:
            self._labels["human"].classes(
                replace=f"status-item {health.human_class}".strip()
            )
        self._set("device", health.device)
        if "device" in self._labels:
            self._labels["device"].classes(
                replace=f"status-item {health.device_class}".strip()
            )
        self._set("clients-status", health.clients)
        self._set("baud", str(params.baudrate))
        self._set("format", serial_format(params))
        self._set(
            "format-note",
            f"{params.data_bits} 数据位 · {PARITY_LABELS.get(params.parity, params.parity)} · {params.stop_bits} 停止位",
        )
        self._set("charset", charset_label(selected.decode))
        self._set("flow", FLOW_LABELS.get(params.flow_control, params.flow_control))
        self._set("humans", f"人端 {selected.human_clients}")
        if "agent" in self._labels:
            self._labels["agent"].set_text(
                f"Agent {'已连接' if selected.agent_connected else '未连接'}"
            )
            self._labels["agent"].classes(
                replace="presence" if selected.agent_connected else "muted"
            )
        self._set("rx", format_bytes(selected.rx_bytes))
        self._set("tx", format_bytes(selected.tx_bytes))
        self._set("last", format_last_rx(selected.last_rx_at, missing=missing))
        self._set(
            "devpath",
            "设备未接入" if missing else f"当前 {view.device_path}",
        )
        self._set(
            "note",
            "本次运行累计；写入设备不代表设备已执行指令。"
            if selected.last_rx_at
            else "尚无设备输出；没有输出本身不能证明参数错误。",
        )
        for line in lines:
            item = line_health(status_to_view(line, self._path_of(line)))
            port = line.human_entry
            self._set(f"rail-state-{port}", item.badge)
            if f"rail-state-{port}" in self._labels:
                self._labels[f"rail-state-{port}"].classes(
                    replace=f"rail-state rail-state-text {item.badge_class}".strip()
                )
            self._set(f"rail-device-{port}", item.device)
            if f"rail-device-{port}" in self._labels:
                self._labels[f"rail-device-{port}"].classes(
                    replace=f"rail-meta rail-device {item.device_class}".strip()
                )
            self._set(f"rail-human-{port}", item.human)
            if f"rail-human-{port}" in self._labels:
                self._labels[f"rail-human-{port}"].classes(
                    replace=f"rail-meta rail-human {item.human_class}".strip()
                )
            self._set(f"rail-clients-{port}", item.clients)
        sig = self._status_sig(selected)
        if "notices" in self._labels and sig != self._notice_sig:
            self._notice_sig = sig
            self._labels["notices"].clear()
            with self._labels["notices"]:
                self._fill_notices(selected, view)

    def _status_sig(self, line: LineStatus) -> tuple[object, ...]:
        """判断提示条要不要重画，避免每秒拆掉通知。"""
        notice = (
            None
            if self._notice is None
            else (self._notice.get("entry"), self._notice.get("title"))
        )
        return (line.human_entry, line.hold, line.human_listening, notice)

    def _rw_class(self, writable: bool, listening: bool) -> str:
        """可读写用正常色，不可写用错误色，人端未监听但设备可写用等待色。"""
        if writable and listening:
            return ""
        if writable:
            return "waiting"
        return "error-color"

    def _seed_views(self, lines: Sequence[LineStatus]) -> None:
        """第一次看见线路时记下快照，避免把初始状态当成恢复。"""
        for line in lines:
            if line.human_entry not in self._views:
                self._views[line.human_entry] = status_to_view(
                    line, self._path_of(line)
                )

    def _track_recovery(self, lines: Sequence[LineStatus]) -> None:
        """设备插回、占用解除或入口恢复监听时给一句反馈，只报一次。"""
        live = {line.human_entry for line in lines}
        for port in [entry for entry in self._views if entry not in live]:
            self._views.pop(port, None)
        for line in lines:
            view = status_to_view(line, self._path_of(line))
            previous = self._views.get(line.human_entry)
            self._views[line.human_entry] = view
            if previous is None:
                continue
            recovered = recovery_notice(previous, view)
            if recovered is None:
                continue
            ui.notify(recovered.title)
            if line.human_entry == self._selected:
                self._notice = {
                    "entry": line.human_entry,
                    "title": recovered.title,
                    "message": recovered.message,
                    "reconnect": False,
                }

    def _retry(self, human_entry: int) -> None:
        """对可恢复状态再占口、再听；不补发旧写入。"""
        try:
            after = self._hub.retry_line(human_entry)
        except KeyError:
            ui.notify("没有这条线路")
            return
        before = self._notice
        self._track_recovery(self._hub.list_lines())
        view = status_to_view(after, self._path_of(after))
        health = line_health(view)
        if health.retry_hold or health.retry_listen:
            ui.notify("仍未恢复，请按提示处理后再试")
        elif self._notice is before:
            ui.notify("线路已恢复")
        self._render_content()

    def _set(self, key: str, text: str) -> None:
        """更新已有标签；控件被拆掉时忽略。"""
        label = self._labels.get(key)
        if label is not None:
            label.set_text(text)

    def _line(self, lines: Sequence[LineStatus]) -> LineStatus:
        """当前选中的线路；没有则第一条。"""
        for line in lines:
            if line.human_entry == self._selected:
                return line
        return lines[0]

    def _path_of(self, line: LineStatus) -> str:
        """此刻 COM 路径；不在现场则空。"""
        return self._list_paths().get(line.device, "")

    def _copy(self, text: str, ok: str) -> None:
        """复制文本到剪贴板。"""
        payload = json.dumps(text, ensure_ascii=False)
        ui.run_javascript(f"navigator.clipboard.writeText({payload})")
        ui.notify(ok)

    def _open_editor(self, human_entry: int | None) -> None:
        """打开新建或完整线路设置；改入口时先占新口，失败保留旧配置。"""
        line = None
        if human_entry is not None:
            for item in self._hub.list_lines():
                if item.human_entry == human_entry:
                    line = item
                    break
        self._editing_entry = human_entry
        self._set_dialog_open(True)
        self._editor.clear()
        with self._editor, ui.card().classes("dialog-card"):
            self._editor_form(line)
        self._editor.open()

    def _editor_form(self, line: LineStatus | None) -> None:
        """完整设置：端口、波特率、数据位、校验、停止位、流控、字符集。"""
        creating = line is None
        used = {item.human_entry for item in self._hub.list_lines()}
        choices = self._device_options(line)
        if line is None:
            seed = default_create_draft(suggest_port(used))
            port_value = seed.port
            name_value = seed.name
            baud_value = seed.baud
            flow_value = seed.flow_control
            bits_value = str(seed.data_bits)
            parity_value = seed.parity
            stop_value = str(seed.stop_bits)
            decode_value = seed.decode
            if choices.hint is not None:
                subtitle = "先接入可用的 USB 转接器，再创建线路。"
            else:
                subtitle = "选择 USB 设备，留一个人端入口。"
        else:
            params = line.serial_params
            port_value = line.human_entry
            name_value = line.name
            baud_value = params.baudrate
            flow_value = params.flow_control
            bits_value = str(params.data_bits)
            parity_value = params.parity
            stop_value = str(params.stop_bits)
            decode_value = line.decode
            subtitle = f"当前入口 {line.human_entry} · 修改后保存生效"
        with ui.element("div").classes("dialoghead"):
            with ui.element("div"):
                ui.html(
                    f"<h2>{'线路设置' if line else '新建线路'}</h2>",
                    sanitize=False,
                )
            ui.label(subtitle)
            self._icon_button("close", self._close_editor, "关闭对话框")
        with ui.element("div").classes("dialog-body"):
            error_box = ui.element("div").classes("notice error").style("display:none")
            with error_box:
                error_title = ui.label("").classes("notice-title")
                error_message = ui.label("")
            self._form["error_box"] = error_box
            self._form["error_title"] = error_title
            self._form["error_message"] = error_message
            if creating and choices.hint is not None:
                with ui.element("section").classes("notice"):
                    ui.label(choices.hint.title).classes("notice-title")
                    ui.label(choices.hint.message)
            self._form["name"] = ui.input(
                "线路名称",
                value=name_value,
                placeholder="例如：AC 控制台",
            ).props("maxlength=32 outlined")
            ui.label("给自己看的名称，不会自动识别转接器后面的机器。").classes(
                "tiny muted"
            )
            with (
                ui.element("div")
                .classes("row")
                .style("display:grid;grid-template-columns:1fr 1fr;gap:14px")
            ):
                self._form["port"] = ui.number(
                    "人端入口端口",
                    value=port_value,
                    min=1,
                    max=65535,
                    format="%.0f",
                ).props("outlined")
                device_options = choices.options or {"": "没有可用设备"}
                self._form["device"] = (
                    ui.select(
                        options=device_options,
                        value=choices.default or "",
                        label="USB 设备",
                    )
                    .props("outlined")
                    .classes("w-full")
                )
                if line is not None or not choices.options:
                    self._form["device"].disable()
            if line is not None:
                device_help = "此线路的设备绑定保持不变。"
            elif choices.hint is not None:
                device_help = (
                    "没有可选设备时无法创建线路。COM 路径会变，请看 USB 身份。"
                )
            else:
                device_help = (
                    "选项同时给出当前 COM 路径和稳定 USB 身份（VID:PID、序列号）。"
                    "已被其他线路使用的设备不可重复选择。"
                )
            ui.label(device_help).classes("tiny muted")
            ui.label("串口参数").classes("form-section")
            with ui.element("div").style(
                "display:grid;grid-template-columns:1fr 1fr;gap:14px"
            ):
                self._form["baud"] = ui.input(
                    "波特率",
                    value=str(baud_value),
                ).props('outlined list="baud-presets"')
                ui.html(
                    "<datalist id='baud-presets'>"
                    + "".join(f"<option value='{n}'></option>" for n in BAUD_PRESETS)
                    + "</datalist>",
                    sanitize=False,
                )
                self._form["flow"] = ui.select(
                    options=dict(FLOW_LABELS),
                    value=flow_value,
                    label="流控",
                ).props("outlined")
            with ui.element("div").style(
                "display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px"
            ):
                self._form["bits"] = ui.select(
                    options={str(n): str(n) for n in ALLOWED_DATA_BITS},
                    value=bits_value,
                    label="数据位",
                ).props("outlined")
                self._form["parity"] = ui.select(
                    options=PARITY_LABELS,
                    value=parity_value,
                    label="校验",
                ).props("outlined")
                self._form["stop"] = ui.select(
                    options={str(n): str(n) for n in ALLOWED_STOP_BITS},
                    value=stop_value,
                    label="停止位",
                ).props("outlined")
            self._form["preview"] = ui.label("").classes("settings-preview")
            ui.label("Agent 文本").classes("form-section")
            self._form["decode"] = ui.select(
                options=CHARSET_LABELS,
                value=decode_value,
                label="Agent 字符集",
            ).props("outlined")
            ui.label(
                "用于 Agent 接收文本的解码，以及发送文本转字节。Moba 等 Telnet 客户端的字符设置需单独配置。"
            ).classes("tiny muted")
            self._form["impact"] = ui.label("").classes("impact")
            self._form["save"] = None
        with ui.element("div").classes("dialog-footer"):
            ui.button("取消", on_click=self._close_editor).props("flat no-caps")
            save = (
                ui.button(
                    "创建线路" if creating else "保存设置",
                    on_click=lambda: self._save_editor(line),
                )
                .props("no-caps unelevated")
                .classes("primary")
            )
            if creating and not choices.options:
                save.disable()
            self._form["save"] = save
        for key in (
            "name",
            "port",
            "device",
            "baud",
            "flow",
            "bits",
            "parity",
            "stop",
            "decode",
        ):
            self._form[key].on(
                "change", lambda _e, current=line: self._refresh_impact(current)
            )
        self._refresh_impact(line)

    def _refresh_impact(self, line: LineStatus | None) -> None:
        """随输入更新串口格式预览和保存影响。"""
        draft = self._read_draft(line)
        if draft is None:
            return
        view = status_to_view(line, self._path_of(line)) if line is not None else None
        impact = impact_text(view, draft, creating=line is None)
        self._form["preview"].set_text(format_preview(draft))
        self._form["impact"].set_text(impact.message)
        self._form["impact"].classes(
            replace="impact warning",
            add="impact warning" if impact.warning else "impact",
        )
        if self._form["save"] is not None:
            self._form["save"].set_text(impact.submit_label)

    def _read_draft(self, line: LineStatus | None) -> Draft | None:
        """从对话框控件读出一份草稿；尚未画完则空。"""
        try:
            port_raw = self._form["port"].value
            baud_raw = str(self._form["baud"].value or "").strip()
            bits_raw = str(self._form["bits"].value)
            stop_raw = str(self._form["stop"].value)
            port = int(port_raw or 0)
            baud = int(baud_raw) if baud_raw.isdigit() else 0
            return Draft(
                name=str(self._form["name"].value or ""),
                port=port,
                baud=baud,
                data_bits=int(bits_raw),
                parity=str(self._form["parity"].value),
                stop_bits=int(stop_raw),
                flow_control=str(self._form["flow"].value),
                decode=str(self._form["decode"].value),
                device_key=str(self._form["device"].value or ""),
            )
        except KeyError, TypeError, ValueError:
            return None

    def _show_form_error(self, title: str, message: str) -> None:
        """就地提示，保留用户输入。"""
        self._form["error_title"].set_text(title)
        self._form["error_message"].set_text(message)
        self._form["error_box"].style("display:block")

    def _save_editor(self, line: LineStatus | None) -> None:
        """校验后创建或保存；失败不出现半条线路。"""
        draft = self._read_draft(line)
        if draft is None:
            self._show_form_error("设置还没读全。", "请检查后再保存。")
            return
        error = validate_draft(draft)
        if error is not None:
            self._show_form_error(error.title, error.message)
            return
        for other in self._hub.list_lines():
            if other.human_entry == draft.port and (
                line is None or other.human_entry != line.human_entry
            ):
                self._show_form_error(
                    f"端口 {draft.port} 已用于另一条线路。",
                    "请选择其他入口。当前设置未发生变化。",
                )
                return
        if line is None:
            assigned = {identity_key(item.device) for item in self._hub.list_lines()}
            if (
                draft.device_key in assigned
                or draft.device_key not in self._present_keys()
            ):
                self._show_form_error(
                    "请选择一台可用的 USB 设备。",
                    "同一台设备只能分配给一条线路，未接入的设备不能新建。"
                    if draft.device_key in assigned
                    else "这台设备已经不在现场。请重新接入后创建线路。",
                )
                return
        try:
            if line is None:
                self._hub.create_line(
                    draft.port,
                    parse_identity_key(draft.device_key),
                    name=draft.name,
                    serial_params=draft_serial_params(draft),
                    decode=draft.decode,
                )
                self._notice = {
                    "entry": draft.port,
                    "title": "线路已创建",
                    "message": (
                        "人端入口已开始监听。请复制人端地址给 Telnet，"
                        "或复制 Agent/MCP 说明交给 Agent。"
                    ),
                    "reconnect": False,
                    "copy_connection": True,
                }
            else:
                old_port = line.human_entry
                port_changed = draft.port != old_port
                params_changed = draft_serial_params(draft) != line.serial_params
                self._hub.change_line(
                    old_port,
                    new_entry=draft.port if port_changed else None,
                    name=draft.name,
                    serial_params=draft_serial_params(draft),
                    decode=draft.decode,
                )
                after = next(
                    item
                    for item in self._hub.list_lines()
                    if item.human_entry == draft.port
                )
                if port_changed:
                    message = "原人端连接已断开，请使用新入口重新接入。"
                    title = f"人端入口已从 {old_port} 改为 {draft.port}"
                elif params_changed and after.hold == LineHold.WAITING:
                    message = "新参数将在设备接入后应用。"
                    title = "线路设置已保存"
                elif params_changed:
                    message = "已按新参数重新占口。"
                    title = "线路设置已保存"
                else:
                    message = "已有连接保持，串口未重新打开。"
                    title = "线路设置已保存"
                self._notice = {
                    "entry": draft.port,
                    "title": title,
                    "message": message,
                    "reconnect": port_changed,
                }
        except HumanEntryOccupied as exc:
            if line is None:
                error = create_port_conflict_error(exc.human_entry)
                self._show_form_error(error.title, error.message)
                return
            kept = (
                f"原线路 {line.human_entry} · {line.serial_params.baudrate} · "
                f"{serial_format(line.serial_params)} · {charset_label(line.decode)} "
                "保持不变，现有连接保留。请更换端口后再保存。"
            )
            self._show_form_error(str(exc), kept)
            return
        except SerialApplyFailed as exc:
            self._show_form_error(str(exc), "原串口参数已保留，请先释放设备后再保存。")
            return
        except ArrangementRejected as exc:
            self._show_form_error(str(exc), "当前设置未发生变化。")
            return
        except KeyError:
            self._show_form_error("没有这条线路", "请关闭对话框后刷新再试。")
            return
        self._selected = draft.port
        self._close_editor()
        self._render_content()

    def _close_editor(self) -> None:
        """关掉设置对话框并恢复定时刷新。"""
        self._editor.close()
        self._set_dialog_open(False)

    def _device_options(self, line: LineStatus | None) -> DeviceChoice:
        """创建设备下拉：可用的在场设备；编辑时只展示当前绑定。"""
        paths = self._list_paths()
        assigned = {item.device for item in self._hub.list_lines()}
        if line is None:
            return create_device_choices(paths, assigned)
        return create_device_choices(
            paths,
            assigned,
            current=line.device,
            current_path=paths.get(line.device, ""),
        )

    def _present_keys(self) -> set[str]:
        """此刻插着的 USB 身份键。"""
        return {identity_key(identity) for identity in self._list_paths()}

    def _open_agent_help(self, line: LineStatus) -> None:
        """展示可复制的 Agent 线路说明。"""
        view = status_to_view(line, self._path_of(line))
        text = agent_share_text(view)
        self._set_dialog_open(True)
        self._confirm.clear()
        with self._confirm, ui.card().classes("dialog-card"):
            with ui.element("div").classes("dialoghead"), ui.element("div"):
                ui.html("<h2>给 Agent 的线路说明</h2>", sanitize=False)
                ui.label("复制后发给已经接入串通的 Agent。")
            with ui.element("div").classes("dialog-body"):
                ui.label(
                    "先在 Agent 工具里配置串通 MCP。下面这段说明用于指明线路，复制本身不会建立连接。"
                ).classes("share-help")
                ui.textarea(value=text).props("readonly outlined").classes("share-text")
            with ui.element("div").classes("dialog-footer"):
                ui.button("关闭", on_click=self._close_confirm).props("flat no-caps")
                ui.button(
                    "复制说明",
                    on_click=lambda: self._copy(text, "Agent 线路说明已复制"),
                ).props("no-caps unelevated").classes("primary")
        self._confirm.open()

    def _confirm_remove(self, human_entry: int) -> None:
        """拆线路前确认；拔掉 USB 不是拆线路。"""
        line = next(
            (
                item
                for item in self._hub.list_lines()
                if item.human_entry == human_entry
            ),
            None,
        )
        if line is None:
            return
        self._set_dialog_open(True)
        self._confirm.clear()
        with self._confirm, ui.card().classes("dialog-card small"):
            with ui.element("div").classes("dialoghead"):
                ui.html(f"<h2>拆掉 {line.human_entry} 线路？</h2>", sanitize=False)
            with ui.element("div").classes("dialog-body"):
                who = ""
                if line.human_clients:
                    who += f"{line.human_clients} 个已连接人端将断开。"
                if line.agent_connected:
                    who += "Agent 将无法继续访问这条线路。"
                ui.label(
                    f"设备会被释放，人端入口 {line.human_entry} 会关闭。{who}"
                ).classes("share-help")
                ui.label(
                    "如果只是设备暂时拔掉，保留线路即可，插回后会自动恢复。"
                ).classes("tiny muted")
            with ui.element("div").classes("dialog-footer"):
                ui.button("保留线路", on_click=self._close_confirm).props(
                    "flat no-caps"
                )
                ui.button(
                    "拆掉线路",
                    on_click=lambda port=human_entry: self._remove(port),
                ).props("no-caps unelevated").classes("danger")
        self._confirm.open()

    def _remove(self, human_entry: int) -> None:
        """拆掉线路并放口。"""
        self._hub.remove_line(human_entry)
        if self._selected == human_entry:
            self._selected = None
        self._notice = None
        self._close_confirm()
        self._render_content()
        ui.notify("线路已拆掉")

    def _close_confirm(self) -> None:
        """关掉确认或说明对话框。"""
        self._confirm.close()
        self._set_dialog_open(False)

    def _open_settings(self) -> None:
        """应用设置：登录后自启。"""
        self._set_dialog_open(True)
        self._confirm.clear()
        with self._confirm, ui.card().classes("dialog-card small"):
            with ui.element("div").classes("dialoghead"), ui.element("div"):
                ui.html("<h2>应用设置</h2>", sanitize=False)
                ui.label("串通常驻，关窗后仍继续运行。")
            with ui.element("div").classes("dialog-body"):
                switch = ui.switch(
                    "登录 Windows 后自动启动",
                    value=self._autostart.is_enabled(),
                )
                ui.label("从托盘“退出串通”才会停止服务并释放全部设备。").classes(
                    "share-help"
                ).style("margin-top:14px")
            with ui.element("div").classes("dialog-footer"):
                ui.button("取消", on_click=self._close_confirm).props("flat no-caps")

                def save() -> None:
                    """写下自启偏好。"""
                    self._autostart.set_enabled(bool(switch.value))
                    self._close_confirm()
                    ui.notify("设置已保存")

                ui.button("保存设置", on_click=save).props(
                    "no-caps unelevated"
                ).classes("primary")
        self._confirm.open()
