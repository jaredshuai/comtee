"""串通管理面板：B 布局渲染适配器，状态与编排流转由 PanelSession 负责。"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from nicegui import ui

from comtee.autostart import AutoStart, PreferredAutoStart
from comtee.hub import Comtee
from comtee.panel_session import (
    ALLOWED_DATA_BITS,
    ALLOWED_STOP_BITS,
    BAUD_PRESETS,
    CHARSET_LABELS,
    FLOW_LABELS,
    PARITY_LABELS,
    Draft,
    EditorState,
    LineDetail,
    PanelSession,
    PanelSnapshot,
    RailItem,
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
    autostart: AutoStart | PreferredAutoStart,
) -> None:
    """画出 B 布局面板。关窗不等于退出，由调用方接托盘。"""
    Panel(hub, autostart).build()


class Panel:
    """NiceGUI 渲染适配器：只绑定控件并把操作转发给 PanelSession。"""

    def __init__(
        self,
        hub: Comtee,
        autostart: AutoStart | PreferredAutoStart,
    ) -> None:
        """注入串通与自启偏好。"""
        self._session = PanelSession(hub)
        self._autostart = autostart
        self._dialog_open = False
        self._device_open = False
        self._rendered_entries: tuple[int, ...] = ()
        self._rendered_selected: int | None = None
        self._rendered_collapsed = False
        self._content: Any = None
        self._split: Any = None
        self._detail: Any = None
        self._labels: dict[str, Any] = {}
        self._editor: Any = None
        self._confirm: Any = None
        self._form: dict[str, Any] = {}
        self._notice_sig: tuple[object, ...] | None = None

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
        self._render_snapshot(self._session.snapshot())
        ui.timer(1.0, self._tick)

    def _set_dialog_open(self, open_: bool) -> None:
        """对话框开着时，定时器不重建输入控件。"""
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
        """按节拍刷新快照，必要时只做增量文案更新。"""
        editor_open = bool(self._editor.value) if self._editor is not None else False
        confirm_open = bool(self._confirm.value) if self._confirm is not None else False
        self._dialog_open = editor_open or confirm_open
        outcome = self._session.tick(dialog_open=self._dialog_open)
        for toast in outcome.toasts:
            ui.notify(toast)
        snapshot = outcome.snapshot
        if snapshot is None:
            return
        if (
            snapshot.entries != self._rendered_entries
            or snapshot.selected_port != self._rendered_selected
            or snapshot.collapsed != self._rendered_collapsed
        ):
            self._render_snapshot(snapshot)
            return
        if snapshot.detail is not None:
            self._patch(snapshot)

    def _render_snapshot(self, snapshot: PanelSnapshot) -> None:
        """按给定快照整块重画主区域（左列表 + 右详情）。"""
        if self._content is None:
            return
        self._rendered_entries = snapshot.entries
        self._rendered_selected = snapshot.selected_port
        self._rendered_collapsed = snapshot.collapsed
        self._labels = {}
        self._content.clear()
        with self._content:
            if snapshot.detail is None:
                self._render_empty()
                self._notice_sig = None
                return
            collapsed = " collapsed" if snapshot.collapsed else ""
            self._split = ui.element("div").classes(f"split{collapsed}")
            with self._split:
                self._render_rail(snapshot.rail, snapshot.collapsed)
                self._detail = ui.element("section").classes("detail")
                with self._detail:
                    self._fill_detail(snapshot.detail)
            self._notice_sig = snapshot.notice_sig

    def _render_empty(self) -> None:
        """还没有线路时的接入说明。"""
        with ui.element("section").classes("empty"):
            ui.html("<h2>接入你的第一条线路</h2>", sanitize=False)
            ui.label(
                "接入 USB 转接器或配对蓝牙串口，为设备留一个人端入口。"
                "人和 Agent 就能从同一条线路接入。"
            )
            ui.button("＋ 新建线路", on_click=lambda: self._open_editor(None)).props(
                "no-caps unelevated"
            ).classes("primary")

    def _render_rail(
        self,
        rail: tuple[RailItem, ...],
        collapsed: bool,
    ) -> None:
        """左侧线路列表；折叠后仍显示名称、入口和状态。"""
        with ui.element("aside").classes("rail"):
            with ui.element("div").classes("railhead"):
                ui.html(
                    f'<h2 class="rail-title-text">我的线路<span class="count">{len(rail)}</span></h2>',
                    sanitize=False,
                )
                self._icon_button(
                    "right" if collapsed else "left",
                    self._toggle_rail,
                    "展开线路栏" if collapsed else "折叠线路栏",
                )
            for item in rail:
                self._rail_item(item)

    def _rail_item(self, item: RailItem) -> None:
        """一条线路的列表项。"""
        port = item.port
        btn = (
            ui.button(on_click=lambda p=port: self._select(p), color=None)
            .props("flat no-caps unelevated")
            .classes("railitem" + (" active" if item.active else ""))
            .tooltip(f"{port} · {item.name} · {item.badge}")
        )
        with btn, ui.element("div").classes("rail-line"):
            with ui.element("div").classes("rail-title"):
                port_label = ui.label(str(port)).classes("mono rail-port")
                name = ui.label(item.name).classes("rail-alias")
            state = ui.label(item.badge).classes(
                f"rail-state rail-state-text {item.badge_class}"
            )
            device = ui.label(item.device).classes(
                f"rail-meta rail-device {item.device_class}"
            )
            human = ui.label(item.human).classes(
                f"rail-meta rail-human {item.human_class}"
            )
            clients = ui.label(item.clients).classes("rail-meta rail-clients")
            self._labels[f"rail-name-{port}"] = name
            self._labels[f"rail-port-{port}"] = port_label
            self._labels[f"rail-state-{port}"] = state
            self._labels[f"rail-device-{port}"] = device
            self._labels[f"rail-human-{port}"] = human
            self._labels[f"rail-clients-{port}"] = clients

    def _select(self, port: int) -> None:
        """切换当前查看的线路，不丢失折叠状态。"""
        self._render_snapshot(self._session.select(port))

    def _toggle_rail(self) -> None:
        """折叠或展开左栏，选中项保持。"""
        self._render_snapshot(self._session.toggle_rail())

    def _fill_detail(self, detail: LineDetail) -> None:
        """右侧详情：先名称、入口和占口，再完整串口参数。"""
        with ui.element("div").classes("detail-top"):
            with ui.element("div").classes("identity"):
                self._labels["alias"] = ui.label(detail.name).classes("line-name")
                ui.label("人端入口").classes("eyebrow")
                self._labels["port"] = ui.label(str(detail.port)).classes("port mono")
            self._labels["badge"] = ui.label(detail.badge).classes(
                f"badge {detail.badge_class}"
            )
        with ui.element("div").classes("endpoint"):
            self._labels["address"] = ui.label(detail.address).classes("mono")
            ui.button(
                "复制地址",
                on_click=lambda addr=detail.address: self._copy(addr, "人端地址已复制"),
                color=None,
            ).props("flat no-caps").classes("quiet link-button")
            ui.button(
                "给 Agent 的说明",
                on_click=lambda d=detail: self._open_agent_help(d),
                color=None,
            ).props("flat no-caps").classes("quiet link-button")
        with ui.element("div").classes("link-status"):
            self._labels["rw"] = ui.label(detail.rw_label).classes(
                f"status-item {detail.rw_class}".strip()
            )
            self._labels["human"] = ui.label(detail.human).classes(
                f"status-item {detail.human_class}".strip()
            )
            self._labels["device"] = ui.label(detail.device).classes(
                f"status-item {detail.device_class}".strip()
            )
            self._labels["clients-status"] = ui.label(detail.clients).classes(
                "status-item"
            )
        self._labels["notices"] = ui.element("div")
        with self._labels["notices"]:
            self._fill_notices(detail)
        with ui.element("div").classes("sectionhead"):
            ui.label("连接参数").classes("section-title")
            ui.button(
                "线路设置 ›",
                on_click=lambda port=detail.port: self._open_editor(port),
                color=None,
            ).props("flat no-caps").classes("quiet link-button")
        with ui.element("div").classes("param-grid"):
            self._param("波特率", detail.baud, "波特 / 秒", "baud")
            self._param(
                "串口格式",
                detail.serial_format,
                detail.format_note,
                "format",
            )
            self._param(
                "Agent 字符集",
                detail.charset,
                "文本接收与发送",
                "charset",
            )
        flow_cls = (
            "flow-control configured"
            if detail.flow != FLOW_LABELS["none"]
            else "flow-control"
        )
        with ui.element("div").classes(flow_cls):
            ui.label("流控")
            self._labels["flow"] = ui.label(detail.flow).classes("flow-value")
        with ui.element("div").classes("clients"):
            ui.label("谁连着").classes("section-title")
            with ui.element("div").classes("client-values"):
                self._labels["humans"] = ui.label(detail.human_clients_text)
                self._labels["agent"] = ui.label(detail.agent_text).classes(
                    detail.agent_class
                )
        with ui.element("div").classes("activity"):
            self._activity("设备接收", detail.rx_text, "rx")
            self._activity("写入设备", detail.tx_text, "tx")
            self._activity("最近收到设备数据", detail.last_rx_text, "last")
        self._labels["note"] = ui.label(detail.activity_note).classes("activity-note")
        with ui.expansion(
            "设备信息",
            value=self._device_open,
            on_value_change=lambda e: setattr(self, "_device_open", bool(e.value)),
        ).classes("device-info"):
            self._labels["devpath"] = ui.label(detail.device_path_text)
            ui.label(f"设备身份  {detail.device_key}").classes("mono")
            self._labels["scansum"] = ui.label(detail.scan_summary).classes(
                "tiny muted"
            )
            ui.label(
                "线路按 USB 或蓝牙硬件身份识别设备，COM 路径可能变化。线路名称由你填写；"
                "设备重新配对后若硬件标识变化，请重新选择设备。"
            ).classes("tiny muted")
        with ui.element("div").classes("detail-bottom"):
            ui.label("关掉窗口后，串通仍在托盘运行。")
            ui.button(
                "拆掉线路",
                on_click=lambda port=detail.port: self._confirm_remove(port),
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

    def _fill_notices(self, detail: LineDetail) -> None:
        """渲染保存结果、恢复反馈和失败动作条。"""
        banner = detail.banner
        if banner is not None:
            copies = detail.connection_copy
            with ui.element("section").classes("notice success"):
                ui.label(banner.title).classes("notice-title")
                ui.label(banner.message)
                if banner.reconnect:
                    ui.label(
                        f"请将 Telnet 书签更新为 {detail.address}；"
                        f"Agent 后续请指名 {detail.port}。"
                    )
                if banner.copy_connection:
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
        for item in detail.failures:
            cls = "notice error" if item.severity == "error" else "notice"
            with ui.element("section").classes(cls):
                ui.label(item.title).classes("notice-title")
                ui.label(item.reason)
                ui.label(item.next_action)
                with ui.element("div").classes("notice-actions"):
                    if item.action:
                        ui.button(
                            item.action_label,
                            on_click=lambda port=detail.port: self._retry(port),
                        ).props("no-caps unelevated")
                    if item.kind == "port":
                        ui.button(
                            "更换入口端口",
                            on_click=lambda port=detail.port: self._open_editor(port),
                        ).props("no-caps unelevated")

    def _dismiss_notice(self) -> None:
        """关掉保存成功或恢复提示条。"""
        self._render_snapshot(self._session.dismiss_notice())

    def _patch(self, snapshot: PanelSnapshot) -> None:
        """仅更新状态与收发文本，不重建 DOM 或破坏交互焦点。"""
        detail = snapshot.detail
        if detail is None:
            return
        self._set("port", str(detail.port))
        self._set("alias", detail.name)
        self._set_labeled("badge", detail.badge, f"badge {detail.badge_class}")
        self._set("address", detail.address)
        self._set_labeled("rw", detail.rw_label, f"status-item {detail.rw_class}")
        self._set_labeled("human", detail.human, f"status-item {detail.human_class}")
        self._set_labeled("device", detail.device, f"status-item {detail.device_class}")
        self._set("clients-status", detail.clients)
        self._set("baud", detail.baud)
        self._set("format", detail.serial_format)
        self._set("format-note", detail.format_note)
        self._set("charset", detail.charset)
        self._set("flow", detail.flow)
        self._set("humans", detail.human_clients_text)
        self._set_labeled("agent", detail.agent_text, detail.agent_class)
        self._set("rx", detail.rx_text)
        self._set("tx", detail.tx_text)
        self._set("last", detail.last_rx_text)
        self._set("devpath", detail.device_path_text)
        self._set("scansum", detail.scan_summary)
        self._set("note", detail.activity_note)
        for item in snapshot.rail:
            port = item.port
            self._set(f"rail-name-{port}", item.name)
            self._set(f"rail-port-{port}", str(port))
            self._set_labeled(
                f"rail-state-{port}",
                item.badge,
                f"rail-state rail-state-text {item.badge_class}",
            )
            self._set_labeled(
                f"rail-device-{port}",
                item.device,
                f"rail-meta rail-device {item.device_class}",
            )
            self._set_labeled(
                f"rail-human-{port}",
                item.human,
                f"rail-meta rail-human {item.human_class}",
            )
            self._set(f"rail-clients-{port}", item.clients)
        if "notices" in self._labels and snapshot.notice_sig != self._notice_sig:
            self._notice_sig = snapshot.notice_sig
            self._labels["notices"].clear()
            with self._labels["notices"]:
                self._fill_notices(detail)

    def _set(self, key: str, text: str) -> None:
        """更新已有标签文案。"""
        label = self._labels.get(key)
        if label is not None:
            label.set_text(text)

    def _set_labeled(self, key: str, text: str, classes: str) -> None:
        """同时更新已有标签的文案与样式类。"""
        label = self._labels.get(key)
        if label is not None:
            label.set_text(text)
            label.classes(replace=classes.strip())

    def _retry(self, port: int) -> None:
        """执行重试恢复并显示提示。"""
        outcome = self._session.retry(port)
        for toast in outcome.toasts:
            ui.notify(toast)
        self._render_snapshot(outcome.snapshot)

    def _copy(self, text: str, ok: str) -> None:
        """复制文本到剪贴板。"""
        payload = json.dumps(text, ensure_ascii=False)
        ui.run_javascript(f"navigator.clipboard.writeText({payload})")
        ui.notify(ok)

    def _open_editor(self, human_entry: int | None) -> None:
        """打开新建或线路设置弹窗。"""
        state = self._session.open_editor(human_entry)
        self._set_dialog_open(True)
        self._form.clear()
        self._editor.clear()
        with self._editor, ui.card().classes("dialog-card"):
            self._render_editor_form(state)
        self._editor.open()

    def _render_editor_form(self, state: EditorState) -> None:
        """按 EditorState 画出表单控件并绑定回调。"""
        draft = state.draft
        with ui.element("div").classes("dialoghead"):
            with ui.element("div"):
                ui.html(f"<h2>{state.title}</h2>", sanitize=False)
            self._form["subtitle"] = ui.label(state.subtitle)
            self._icon_button("close", self._close_editor, "关闭对话框")
        with ui.element("div").classes("dialog-body"):
            error_box = ui.element("div").classes("notice error").style("display:none")
            with error_box:
                error_title = ui.label("").classes("notice-title")
                error_message = ui.label("")
            self._form["error_box"] = error_box
            self._form["error_title"] = error_title
            self._form["error_message"] = error_message
            if state.creating:
                hint_box = ui.element("section").classes("notice")
                if state.empty_hint is None:
                    hint_box.style("display:none")
                with hint_box:
                    hint_title = ui.label(
                        state.empty_hint.title if state.empty_hint is not None else ""
                    ).classes("notice-title")
                    hint_message = ui.label(
                        state.empty_hint.message if state.empty_hint is not None else ""
                    )
                    action_label = (
                        state.empty_hint.action_label
                        if state.empty_hint is not None
                        and state.empty_hint.action_label
                        else "重新扫描设备"
                    )
                    with ui.element("div").classes("notice-actions"):
                        ui.button(
                            action_label,
                            on_click=self._rescan_create_devices,
                        ).props("no-caps unelevated")
                self._form["device_hint_box"] = hint_box
                self._form["device_hint_title"] = hint_title
                self._form["device_hint_message"] = hint_message
            self._form["name"] = ui.input(
                "线路名称",
                value=draft.name,
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
                    value=draft.port,
                    min=1,
                    max=65535,
                    format="%.0f",
                ).props("outlined")
                self._form["device"] = (
                    ui.select(
                        options=state.device_options,
                        value=draft.device_key,
                        label="串口设备",
                    )
                    .props("outlined")
                    .classes("w-full")
                )
                if state.device_disabled:
                    self._form["device"].disable()
            self._form["device_help"] = ui.label(state.device_help).classes(
                "tiny muted"
            )
            if state.creating:
                rescan_quiet = (
                    ui.button(
                        "重新扫描设备",
                        on_click=self._rescan_create_devices,
                    )
                    .props("flat no-caps")
                    .classes("quiet link-button")
                )
                if not state.show_quiet_rescan:
                    rescan_quiet.style("display:none")
                self._form["device_rescan_quiet"] = rescan_quiet
            ui.label("串口参数").classes("form-section")
            with ui.element("div").style(
                "display:grid;grid-template-columns:1fr 1fr;gap:14px"
            ):
                self._form["baud"] = ui.input(
                    "波特率",
                    value=str(draft.baud),
                ).props('outlined list="baud-presets"')
                ui.html(
                    "<datalist id='baud-presets'>"
                    + "".join(f"<option value='{n}'></option>" for n in BAUD_PRESETS)
                    + "</datalist>",
                    sanitize=False,
                )
                self._form["flow"] = ui.select(
                    options=dict(FLOW_LABELS),
                    value=draft.flow_control,
                    label="流控",
                ).props("outlined")
            with ui.element("div").style(
                "display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px"
            ):
                self._form["bits"] = ui.select(
                    options={str(n): str(n) for n in ALLOWED_DATA_BITS},
                    value=str(draft.data_bits),
                    label="数据位",
                ).props("outlined")
                self._form["parity"] = ui.select(
                    options=PARITY_LABELS,
                    value=draft.parity,
                    label="校验",
                ).props("outlined")
                self._form["stop"] = ui.select(
                    options={str(n): str(n) for n in ALLOWED_STOP_BITS},
                    value=str(draft.stop_bits),
                    label="停止位",
                ).props("outlined")
            self._form["preview"] = ui.label(state.preview.format_preview).classes(
                "settings-preview"
            )
            ui.label("Agent 文本").classes("form-section")
            self._form["decode"] = ui.select(
                options=CHARSET_LABELS,
                value=draft.decode,
                label="Agent 字符集",
            ).props("outlined")
            ui.label(
                "用于 Agent 接收文本的解码，以及发送文本转字节。Moba 等 Telnet 客户端的字符设置需单独配置。"
            ).classes("tiny muted")
        self._form["impact"] = ui.label(state.preview.impact.message).classes(
            "impact impact-bar warning"
            if state.preview.impact.warning
            else "impact impact-bar"
        )
        with ui.element("div").classes("dialog-footer"):
            ui.button("取消", on_click=self._close_editor).props("flat no-caps")
            save = (
                ui.button(
                    state.preview.impact.submit_label,
                    on_click=lambda editing=state.editing_port: self._save_editor(
                        editing
                    ),
                )
                .props("no-caps unelevated")
                .classes("primary")
            )
            if not state.can_save:
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
                "change",
                lambda _e, editing=state.editing_port: self._refresh_impact(editing),
            )

    def _refresh_impact(self, editing_port: int | None) -> None:
        """随输入更新串口格式预览和保存影响。"""
        draft = self._read_draft()
        if draft is None:
            return
        preview = self._session.preview_editor(editing_port, draft)
        self._form["preview"].set_text(preview.format_preview)
        self._form["impact"].set_text(preview.impact.message)
        self._form["impact"].classes(
            replace=(
                "impact impact-bar warning"
                if preview.impact.warning
                else "impact impact-bar"
            ),
        )
        if self._form["save"] is not None:
            self._form["save"].set_text(preview.impact.submit_label)

    def _rescan_create_devices(self) -> None:
        """弹窗内重扫现场设备，保留已填表单字段。"""
        state = self._session.rescan_create(self._read_draft())
        device = self._form["device"]
        device.set_options(state.device_options, value=state.draft.device_key)
        if state.device_disabled:
            device.disable()
        else:
            device.enable()
        save = self._form.get("save")
        if save is not None:
            if state.can_save:
                save.enable()
            else:
                save.disable()
            save.set_text(state.preview.impact.submit_label)
        if state.empty_hint is not None:
            self._form["device_hint_title"].set_text(state.empty_hint.title)
            self._form["device_hint_message"].set_text(state.empty_hint.message)
            self._form["device_hint_box"].style("display:block")
            self._form["device_rescan_quiet"].style("display:none")
        else:
            self._form["device_hint_box"].style("display:none")
            self._form["device_rescan_quiet"].style("display:inline-flex")
        self._form["device_help"].set_text(state.device_help)
        self._form["subtitle"].set_text(state.subtitle)
        self._form["preview"].set_text(state.preview.format_preview)
        self._form["impact"].set_text(state.preview.impact.message)
        self._form["impact"].classes(
            replace=(
                "impact impact-bar warning"
                if state.preview.impact.warning
                else "impact impact-bar"
            ),
        )

    def _read_draft(self) -> Draft | None:
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
        """就地提示错误，保留用户输入。"""
        self._form["error_title"].set_text(title)
        self._form["error_message"].set_text(message)
        self._form["error_box"].style("display:block")

    def _save_editor(self, editing_port: int | None) -> None:
        """把表单提交给 PanelSession；失败则就地提示。"""
        outcome = self._session.submit_editor(editing_port, self._read_draft())
        if not outcome.ok:
            if outcome.error is not None:
                self._show_form_error(outcome.error.title, outcome.error.message)
            return
        self._close_editor()
        if outcome.snapshot is not None:
            self._render_snapshot(outcome.snapshot)

    def _close_editor(self) -> None:
        """关掉设置对话框并恢复定时刷新。"""
        self._editor.close()
        self._set_dialog_open(False)

    def _open_agent_help(self, detail: LineDetail) -> None:
        """展示可复制的 Agent 线路说明。"""
        text = detail.agent_share_text
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
        """拆线路前确认；拔掉设备不是拆线路。"""
        impact = self._session.remove_prompt(human_entry)
        if impact is None:
            return
        self._set_dialog_open(True)
        self._confirm.clear()
        with self._confirm, ui.card().classes("dialog-card small"):
            with ui.element("div").classes("dialoghead"):
                ui.html(f"<h2>{impact.title}</h2>", sanitize=False)
            with ui.element("div").classes("dialog-body"):
                ui.label(impact.message).classes("share-help")
                ui.label(impact.keep_hint).classes("tiny muted")
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
        outcome = self._session.remove(human_entry)
        self._close_confirm()
        self._render_snapshot(outcome.snapshot)
        for toast in outcome.toasts:
            ui.notify(toast)

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
