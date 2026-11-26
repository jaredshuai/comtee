"""面板深模块：收拢线路编排状态机、扫描快照、影响预估、异常转译与恢复反馈。"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from comtee.hub import (
    ArrangementRejected,
    BluetoothIdentity,
    Comtee,
    HumanEntryOccupied,
    LineHold,
    LineStatus,
    SerialApplyFailed,
    SerialIdentity,
    SerialParams,
    SerialScan,
    UsbIdentity,
)

ALLOWED_DATA_BITS = (5, 6, 7, 8)
ALLOWED_PARITY = ("N", "E", "O")
ALLOWED_STOP_BITS = (1, 2)
ALLOWED_FLOW = ("none", "rtscts", "xonxoff", "dsrdtr")
ALLOWED_CHARSETS = ("gbk", "utf-8")
BAUD_PRESETS = (9600, 19200, 38400, 57600, 115200)

_NAME_MAX = 32
_PORT_MIN = 1
_PORT_MAX = 65535
_MCP_COMMAND = "python -m comtee.mcp"
_AGENT_PIPE = r"\\.\pipe\comtee"

PARITY_LABELS = {"N": "无校验", "E": "偶校验", "O": "奇校验"}
FLOW_LABELS = {
    "none": "无流控",
    "rtscts": "RTS/CTS · 硬件流控",
    "xonxoff": "XON/XOFF · 软件流控",
    "dsrdtr": "DSR/DTR · 硬件流控",
}
CHARSET_LABELS = {"gbk": "GBK", "utf-8": "UTF-8"}


@dataclass(frozen=True)
class Draft:
    """面板编辑中的一份线路设置。"""

    name: str
    port: int
    baud: int
    data_bits: int
    parity: str
    stop_bits: int
    flow_control: str
    decode: str
    device_key: str


@dataclass(frozen=True)
class FieldError:
    """保存或校验失败时的错误提示。"""

    field: str
    title: str
    message: str


@dataclass(frozen=True)
class Impact:
    """保存前告诉操作员的影响说明。"""

    message: str
    warning: bool
    submit_label: str
    reopens_serial: bool = False


@dataclass(frozen=True)
class DeviceHint:
    """新建线路没有可用设备时的可行动提示。"""

    title: str
    message: str
    action: str = ""
    action_label: str = ""


@dataclass(frozen=True)
class ConnectionCopy:
    """可直接复制的人端地址与 Agent/MCP 说明。"""

    address: str
    address_label: str
    agent_text: str
    agent_label: str


@dataclass(frozen=True)
class BannerNotice:
    """详情页顶部的保存成功或状态恢复通知。"""

    entry: int
    title: str
    message: str
    reconnect: bool = False
    copy_connection: bool = False


@dataclass(frozen=True)
class FailureCard:
    """故障状态的原因、下一步与恢复动作。"""

    kind: str
    title: str
    reason: str
    next_action: str
    action: str
    action_label: str
    severity: str


@dataclass(frozen=True)
class RemovePrompt:
    """拆线路前的确认文案。"""

    title: str
    message: str
    keep_hint: str


@dataclass(frozen=True)
class RailItem:
    """左侧线路列表的一行（含折叠态与展开态所需文案）。"""

    port: int
    name: str
    badge: str
    badge_class: str
    device: str
    device_class: str
    human: str
    human_class: str
    clients: str
    active: bool


@dataclass(frozen=True)
class LineDetail:
    """当前选中线路右侧详情页所需的全部已派生文本。"""

    port: int
    name: str
    badge: str
    badge_class: str
    address: str
    rw_label: str
    rw_class: str
    human: str
    human_class: str
    device: str
    device_class: str
    clients: str
    baud: str
    serial_format: str
    format_note: str
    charset: str
    flow: str
    human_clients_text: str
    agent_text: str
    agent_class: str
    rx_text: str
    tx_text: str
    last_rx_text: str
    activity_note: str
    device_path_text: str
    device_key: str
    scan_summary: str
    agent_share_text: str
    connection_copy: ConnectionCopy
    banner: BannerNotice | None
    failures: tuple[FailureCard, ...]
    retry_hold: bool
    retry_listen: bool


@dataclass(frozen=True)
class PanelSnapshot:
    """面板单次渲染所需的完整只读快照。"""

    entries: tuple[int, ...]
    selected_port: int | None
    collapsed: bool
    rail: tuple[RailItem, ...]
    detail: LineDetail | None
    notice_sig: tuple[object, ...] | None


@dataclass(frozen=True)
class TickOutcome:
    """定时刷新结果：对话框打开时跳过快照更新，避免拆掉输入。"""

    snapshot: PanelSnapshot | None
    toasts: tuple[str, ...]


@dataclass(frozen=True)
class ActionOutcome:
    """重试或拆线路等操作后的快照与即时提示。"""

    snapshot: PanelSnapshot
    toasts: tuple[str, ...]


@dataclass(frozen=True)
class EditorPreview:
    """编辑弹窗里随输入更新的串口格式预览与保存影响。"""

    format_preview: str
    impact: Impact


@dataclass(frozen=True)
class EditorState:
    """打开或重扫新建/编辑对话框所需的完整状态。"""

    creating: bool
    editing_port: int | None
    title: str
    subtitle: str
    draft: Draft
    device_options: dict[str, str]
    device_disabled: bool
    device_help: str
    empty_hint: DeviceHint | None
    show_quiet_rescan: bool
    can_save: bool
    preview: EditorPreview


@dataclass(frozen=True)
class SaveOutcome:
    """提交新建或线路设置的 outcome；失败保留旧线路状态。"""

    ok: bool
    snapshot: PanelSnapshot | None = None
    error: FieldError | None = None


@dataclass(frozen=True)
class _LineView:
    """内部对齐视图：把 LineStatus 与同一时刻的 SerialScan 拼在一起。"""

    human_entry: int
    name: str
    hold: LineHold
    human_listening: bool
    human_clients: int
    agent_connected: bool
    serial_params: SerialParams
    decode: str
    device_key: str
    device_path: str
    usb_ports: int = 0
    bluetooth_ports: int = 0
    unidentified_ports: int = 0
    rx_bytes: int = 0
    tx_bytes: int = 0
    last_rx_at: float | None = None


@dataclass(frozen=True)
class _LineHealth:
    """分项状态：设备、人端监听、客户端与可否读写。"""

    writable: bool
    rw_label: str
    badge: str
    badge_class: str
    device: str
    device_class: str
    human: str
    human_class: str
    clients: str
    retry_hold: bool
    retry_listen: bool


@dataclass(frozen=True)
class _DeviceChoice:
    """设备下拉候选项与空设备提示。"""

    options: dict[str, str]
    default: str | None
    hint: DeviceHint | None


class PanelSession:
    """面板会话控制器：独占面板状态与编排流转，面向 Comtee 与内存测试无缝复用。"""

    def __init__(self, hub: Comtee) -> None:
        """绑定串通实例并初始化选中态、折叠态与恢复追踪。"""
        self._hub = hub
        self._selected: int | None = None
        self._collapsed = False
        self._notice: BannerNotice | None = None
        self._views: dict[int, _LineView] = {}

    def snapshot(self) -> PanelSnapshot:
        """生成当前最新快照；首见线路只记基线，不误报恢复。"""
        lines = self._hub.list_lines()
        scan = self._hub.last_scan()
        self._seed_views(lines, scan)
        return self._build_snapshot(lines, scan)

    def tick(self, *, dialog_open: bool = False) -> TickOutcome:
        """对照现场并追踪一次性恢复通知；对话框打开时只刷新串通。"""
        self._hub.refresh()
        if dialog_open:
            return TickOutcome(snapshot=None, toasts=())
        lines = self._hub.list_lines()
        scan = self._hub.last_scan()
        toasts = self._track_recovery(lines, scan)
        return TickOutcome(
            snapshot=self._build_snapshot(lines, scan),
            toasts=toasts,
        )

    def select(self, port: int) -> PanelSnapshot:
        """切换右侧详情选中的线路，保留折叠状态。"""
        self._selected = port
        if self._notice is not None and self._notice.entry != port:
            self._notice = None
        return self.snapshot()

    def toggle_rail(self) -> PanelSnapshot:
        """折叠或展开左侧线路栏，保留选中线路。"""
        self._collapsed = not self._collapsed
        return self.snapshot()

    def dismiss_notice(self) -> PanelSnapshot:
        """关掉当前保存或恢复提示条。"""
        self._notice = None
        return self.snapshot()

    def retry(self, port: int) -> ActionOutcome:
        """对冲突状态执行重试占口/重绑人端入口，不补发旧写入。"""
        try:
            after = self._hub.retry_line(port)
        except KeyError:
            return ActionOutcome(
                snapshot=self.snapshot(),
                toasts=("没有这条线路",),
            )
        before_notice = self._notice
        lines = self._hub.list_lines()
        scan = self._hub.last_scan()
        toasts = list(self._track_recovery(lines, scan))
        health = _line_health(_to_view(after, scan))
        if health.retry_hold or health.retry_listen:
            toasts.append("仍未恢复，请按提示处理后再试")
        elif self._notice is before_notice:
            toasts.append("线路已恢复")
        return ActionOutcome(
            snapshot=self._build_snapshot(lines, scan),
            toasts=tuple(toasts),
        )

    def remove_prompt(self, port: int) -> RemovePrompt | None:
        """生成拆掉指定线路前的确认提示文案。"""
        line = next(
            (item for item in self._hub.list_lines() if item.human_entry == port),
            None,
        )
        if line is None:
            return None
        extras = ""
        if line.human_clients:
            extras += f"{line.human_clients} 个已连接人端将断开。"
        if line.agent_connected:
            extras += "Agent 将无法继续访问这条线路。"
        return RemovePrompt(
            title=f"拆掉 {line.human_entry} 线路？",
            message=(
                f"确认后会停止人端入口 {line.human_entry} 的监听，"
                f"并释放这台设备的占口。{extras}"
            ),
            keep_hint="如果只是设备暂时拔掉，保留线路即可，插回后会自动恢复。",
        )

    def remove(self, port: int) -> ActionOutcome:
        """拆掉线路、释放设备并回到有效选中状态。"""
        self._hub.remove_line(port)
        self._views.pop(port, None)
        if self._selected == port:
            self._selected = None
        self._notice = None
        return ActionOutcome(
            snapshot=self.snapshot(),
            toasts=("线路已拆掉",),
        )

    def open_editor(self, port: int | None = None) -> EditorState:
        """打开新建或线路设置弹窗，执行一次现场扫描生成可选设备与初值。"""
        lines = self._hub.list_lines()
        scan = self._hub.scan()
        line = (
            next((item for item in lines if item.human_entry == port), None)
            if port is not None
            else None
        )
        assigned = {item.device for item in lines}
        used = {item.human_entry for item in lines}
        if line is None:
            choices = _create_device_choices(
                scan.paths,
                assigned,
                unidentified_ports=scan.unidentified,
            )
            draft = _default_create_draft(
                _suggest_port(used),
                device_key=choices.default or "",
            )
            return self._build_create_editor_state(choices, draft)
        choices = _create_device_choices(
            scan.paths,
            assigned,
            current=line.device,
            current_path=scan.paths.get(line.device, ""),
        )
        params = line.serial_params
        draft = Draft(
            name=line.name,
            port=line.human_entry,
            baud=params.baudrate,
            data_bits=params.data_bits,
            parity=params.parity,
            stop_bits=params.stop_bits,
            flow_control=params.flow_control,
            decode=line.decode,
            device_key=choices.default or _identity_key(line.device),
        )
        view = _to_view(line, scan)
        return EditorState(
            creating=False,
            editing_port=line.human_entry,
            title="线路设置",
            subtitle=f"当前入口 {line.human_entry} · 修改后保存生效",
            draft=draft,
            device_options=choices.options or {"": "没有可用设备"},
            device_disabled=not choices.options,
            device_help="需要更换转接器或蓝牙重新配对后，可在此重新选择当前可用设备。",
            empty_hint=None,
            show_quiet_rescan=False,
            can_save=True,
            preview=self._build_preview(view, draft, creating=False),
        )

    def preview_editor(self, editing_port: int | None, draft: Draft) -> EditorPreview:
        """随表单输入重算串口格式预览与保存影响提示。"""
        view = self._current_view(editing_port) if editing_port is not None else None
        return self._build_preview(view, draft, creating=editing_port is None)

    def rescan_create(self, draft: Draft | None) -> EditorState:
        """新建弹窗内重扫现场串口设备；保留已填名称、入口和串口参数。"""
        lines = self._hub.list_lines()
        scan = self._hub.scan()
        assigned = {item.device for item in lines}
        choices = _create_device_choices(
            scan.paths,
            assigned,
            unidentified_ports=scan.unidentified,
        )
        next_key = choices.default if choices.default else ""
        base = (
            draft
            if draft is not None
            else _default_create_draft(
                _suggest_port({item.human_entry for item in lines})
            )
        )
        updated_draft = Draft(
            name=base.name,
            port=base.port,
            baud=base.baud,
            data_bits=base.data_bits,
            parity=base.parity,
            stop_bits=base.stop_bits,
            flow_control=base.flow_control,
            decode=base.decode,
            device_key=next_key,
        )
        return self._build_create_editor_state(choices, updated_draft)

    def submit_editor(
        self,
        editing_port: int | None,
        draft: Draft | None,
    ) -> SaveOutcome:
        """校验并提交新建或线路编辑；失败保留原编排、原监听和原占口。"""
        if draft is None:
            return SaveOutcome(
                ok=False,
                error=FieldError("", "设置还没读全。", "请检查后再保存。"),
            )
        error = _validate_draft(draft)
        if error is not None:
            return SaveOutcome(ok=False, error=error)
        lines = self._hub.list_lines()
        for other in lines:
            if other.human_entry == draft.port and (
                editing_port is None or other.human_entry != editing_port
            ):
                return SaveOutcome(
                    ok=False,
                    error=FieldError(
                        "port",
                        f"端口 {draft.port} 已用于另一条线路。",
                        "请选择其他入口。当前设置未发生变化。",
                    ),
                )
        if editing_port is None:
            return self._submit_create(lines, draft)
        return self._submit_edit(lines, editing_port, draft)

    def _submit_create(
        self,
        lines: tuple[LineStatus, ...],
        draft: Draft,
    ) -> SaveOutcome:
        """处理新建线路提交，先核对设备未分配且在场。"""
        scan = self._hub.scan()
        assigned = {_identity_key(item.device) for item in lines}
        present = {_identity_key(identity) for identity in scan.paths}
        if draft.device_key in assigned or draft.device_key not in present:
            return SaveOutcome(
                ok=False,
                error=FieldError(
                    "device",
                    "请选择一台可用的串口设备。",
                    "同一台设备只能分配给一条线路，未接入的设备不能新建。"
                    if draft.device_key in assigned
                    else "这台设备已经不在现场。请重新接入后创建线路。",
                ),
            )
        try:
            self._hub.create_line(
                draft.port,
                _parse_identity_key(draft.device_key),
                name=draft.name,
                serial_params=_draft_serial_params(draft),
                decode=draft.decode,
            )
        except HumanEntryOccupied as exc:
            return SaveOutcome(
                ok=False,
                error=FieldError(
                    "port",
                    f"人端入口 {exc.human_entry} 被其他程序占用",
                    "线路尚未创建，设备尚未被这条线路占用。请更换端口后再试。",
                ),
            )
        except ArrangementRejected as exc:
            return SaveOutcome(
                ok=False,
                error=FieldError("", str(exc), "当前设置未发生变化。"),
            )
        self._notice = BannerNotice(
            entry=draft.port,
            title="线路已创建",
            message=(
                "人端入口已开始监听。请复制人端地址给 Telnet，"
                "或复制 Agent/MCP 说明交给 Agent。"
            ),
            copy_connection=True,
        )
        self._selected = draft.port
        return SaveOutcome(ok=True, snapshot=self.snapshot())

    def _submit_edit(
        self,
        lines: tuple[LineStatus, ...],
        editing_port: int,
        draft: Draft,
    ) -> SaveOutcome:
        """处理已有线路编辑；明确区分端口迁移、换设备和改参数回滚原因。"""
        line = next(
            (item for item in lines if item.human_entry == editing_port),
            None,
        )
        if line is None:
            return SaveOutcome(
                ok=False,
                error=FieldError("", "没有这条线路", "请关闭对话框后刷新再试。"),
            )
        old_port = line.human_entry
        port_changed = draft.port != old_port
        params = _draft_serial_params(draft)
        params_changed = params != line.serial_params
        device_changed = bool(draft.device_key) and draft.device_key != _identity_key(
            line.device
        )
        new_device = _parse_identity_key(draft.device_key) if device_changed else None
        try:
            self._hub.change_line(
                old_port,
                new_entry=draft.port if port_changed else None,
                device=new_device,
                name=draft.name,
                serial_params=params,
                decode=draft.decode,
            )
        except HumanEntryOccupied as exc:
            kept = (
                f"原线路 {line.human_entry} · {line.serial_params.baudrate} · "
                f"{_serial_format(line.serial_params)} · {_charset_label(line.decode)} "
                "保持不变，现有连接保留。请更换端口后再保存。"
            )
            return SaveOutcome(ok=False, error=FieldError("port", str(exc), kept))
        except SerialApplyFailed as exc:
            detail = (
                "原设备绑定已保留，请先释放新设备后再保存。"
                if device_changed
                else "原串口参数已保留，请先释放设备后再保存。"
            )
            return SaveOutcome(ok=False, error=FieldError("", str(exc), detail))
        except ArrangementRejected as exc:
            return SaveOutcome(
                ok=False,
                error=FieldError("", str(exc), "当前设置未发生变化。"),
            )
        except KeyError:
            return SaveOutcome(
                ok=False,
                error=FieldError("", "没有这条线路", "请关闭对话框后刷新再试。"),
            )
        after = next(
            item for item in self._hub.list_lines() if item.human_entry == draft.port
        )
        if port_changed:
            title = f"人端入口已从 {old_port} 改为 {draft.port}"
            message = "原人端连接已断开，请使用新入口重新接入。"
        elif device_changed and after.hold == LineHold.WAITING:
            title = "线路设置已保存"
            message = "设备绑定已更新，新设备将在接入后占口。"
        elif device_changed:
            title = "线路设置已保存"
            message = "已切换到新设备并重新占口。"
        elif params_changed and after.hold == LineHold.WAITING:
            title = "线路设置已保存"
            message = "新参数将在设备接入后应用。"
        elif params_changed:
            title = "线路设置已保存"
            message = "已按新参数重新占口。"
        else:
            title = "线路设置已保存"
            message = "已有连接保持，串口未重新打开。"
        self._notice = BannerNotice(
            entry=draft.port,
            title=title,
            message=message,
            reconnect=port_changed,
        )
        self._selected = draft.port
        return SaveOutcome(ok=True, snapshot=self.snapshot())

    def _build_create_editor_state(
        self,
        choices: _DeviceChoice,
        draft: Draft,
    ) -> EditorState:
        """拼出新建线路表单状态。"""
        has_devices = bool(choices.options)
        if choices.hint is not None:
            subtitle = "先接入 USB 转接器或配对蓝牙串口，再创建线路。"
            device_help = "没有可选设备时无法创建线路。COM 路径会变，请看设备身份。"
        else:
            subtitle = "选择 USB 或蓝牙串口，留一个人端入口。"
            device_help = (
                "选项同时给出当前 COM 路径和稳定设备身份（USB VID:PID/序列号或蓝牙硬件标识）。"
                "已被其他线路使用的设备不可重复选择。"
            )
        return EditorState(
            creating=True,
            editing_port=None,
            title="新建线路",
            subtitle=subtitle,
            draft=draft,
            device_options=choices.options or {"": "没有可用设备"},
            device_disabled=not has_devices,
            device_help=device_help,
            empty_hint=choices.hint,
            show_quiet_rescan=choices.hint is None,
            can_save=has_devices,
            preview=self._build_preview(None, draft, creating=True),
        )

    def _build_preview(
        self,
        view: _LineView | None,
        draft: Draft,
        *,
        creating: bool,
    ) -> EditorPreview:
        """统一计算串口格式预览和保存影响。"""
        return EditorPreview(
            format_preview=_format_preview(draft),
            impact=_impact_text(view, draft, creating=creating),
        )

    def _current_view(self, human_entry: int) -> _LineView | None:
        """取指定线路与最近扫描对齐后的视图。"""
        scan = self._hub.last_scan()
        for item in self._hub.list_lines():
            if item.human_entry == human_entry:
                return _to_view(item, scan)
        return None

    def _prune_dead_views(self, lines: Sequence[LineStatus]) -> None:
        """清掉已拆除线路的历史视图缓存。"""
        live = {line.human_entry for line in lines}
        for port in [entry for entry in self._views if entry not in live]:
            self._views.pop(port, None)

    def _seed_views(
        self,
        lines: Sequence[LineStatus],
        scan: SerialScan,
    ) -> None:
        """首次见到线路时记下快照，避免误将初态当恢复。"""
        self._prune_dead_views(lines)
        for line in lines:
            if line.human_entry not in self._views:
                self._views[line.human_entry] = _to_view(line, scan)

    def _track_recovery(
        self,
        lines: Sequence[LineStatus],
        scan: SerialScan,
    ) -> tuple[str, ...]:
        """状态从等待或冲突恢复时生成一次性提示条与 Toast。"""
        self._prune_dead_views(lines)
        toasts: list[str] = []
        for line in lines:
            view = _to_view(line, scan)
            previous = self._views.get(line.human_entry)
            self._views[line.human_entry] = view
            if previous is None:
                continue
            recovered = _recovery_notice(previous, view)
            if recovered is None:
                continue
            title, message = recovered
            toasts.append(title)
            if line.human_entry == self._selected:
                self._notice = BannerNotice(
                    entry=line.human_entry,
                    title=title,
                    message=message,
                )
        return tuple(toasts)

    def _build_snapshot(
        self,
        lines: Sequence[LineStatus],
        scan: SerialScan,
    ) -> PanelSnapshot:
        """从串通状态与最近一次扫描构造完整面板快照。"""
        entries = tuple(line.human_entry for line in lines)
        if not entries:
            self._selected = None
            return PanelSnapshot(
                entries=(),
                selected_port=None,
                collapsed=self._collapsed,
                rail=(),
                detail=None,
                notice_sig=None,
            )
        if self._selected not in entries:
            self._selected = entries[0]
        selected = next(line for line in lines if line.human_entry == self._selected)
        rail = tuple(
            _build_rail_item(
                _to_view(line, scan),
                active=line.human_entry == selected.human_entry,
            )
            for line in lines
        )
        selected_view = _to_view(selected, scan)
        banner = (
            self._notice
            if self._notice is not None and self._notice.entry == selected.human_entry
            else None
        )
        detail = _build_detail(selected_view, banner)
        notice_sig = (
            selected.human_entry,
            selected.hold,
            selected.human_listening,
            None if banner is None else (banner.entry, banner.title),
        )
        return PanelSnapshot(
            entries=entries,
            selected_port=selected.human_entry,
            collapsed=self._collapsed,
            rail=rail,
            detail=detail,
            notice_sig=notice_sig,
        )


def _to_view(line: LineStatus, scan: SerialScan) -> _LineView:
    """将 LineStatus 与 SerialScan 合并为内部对齐视图。"""
    return _LineView(
        human_entry=line.human_entry,
        name=line.name,
        hold=line.hold,
        human_listening=line.human_listening,
        human_clients=line.human_clients,
        agent_connected=line.agent_connected,
        serial_params=line.serial_params,
        decode=line.decode,
        device_key=_identity_key(line.device),
        device_path=scan.paths.get(line.device, ""),
        usb_ports=scan.usb,
        bluetooth_ports=scan.bluetooth,
        unidentified_ports=scan.unidentified,
        rx_bytes=line.rx_bytes,
        tx_bytes=line.tx_bytes,
        last_rx_at=line.last_rx_at,
    )


def _build_rail_item(view: _LineView, *, active: bool) -> RailItem:
    """构建左侧线路列表单行视图模型。"""
    health = _line_health(view)
    return RailItem(
        port=view.human_entry,
        name=_line_display_name(view.name),
        badge=health.badge,
        badge_class=health.badge_class,
        device=health.device,
        device_class=health.device_class,
        human=health.human,
        human_class=health.human_class,
        clients=health.clients,
        active=active,
    )


def _build_detail(view: _LineView, banner: BannerNotice | None) -> LineDetail:
    """构建右侧详情页所需的所有衍生文本。"""
    health = _line_health(view)
    params = view.serial_params
    missing = view.hold == LineHold.WAITING
    address = _listen_address(view.human_entry)
    share_text = _agent_share_text(view)
    return LineDetail(
        port=view.human_entry,
        name=_line_display_name(view.name),
        badge=health.badge,
        badge_class=health.badge_class,
        address=address,
        rw_label=health.rw_label,
        rw_class=_rw_class(health.writable, view.human_listening),
        human=health.human,
        human_class=health.human_class,
        device=health.device,
        device_class=health.device_class,
        clients=health.clients,
        baud=str(params.baudrate),
        serial_format=_serial_format(params),
        format_note=_format_note(params),
        charset=_charset_label(view.decode),
        flow=FLOW_LABELS.get(params.flow_control, params.flow_control),
        human_clients_text=f"人端 {view.human_clients}",
        agent_text=f"Agent {'已连接' if view.agent_connected else '未连接'}",
        agent_class="presence" if view.agent_connected else "muted",
        rx_text=_format_bytes(view.rx_bytes),
        tx_text=_format_bytes(view.tx_bytes),
        last_rx_text=_format_last_rx(view.last_rx_at, missing=missing),
        activity_note=(
            "本次运行累计；写入设备不代表设备已执行指令。"
            if view.last_rx_at
            else "尚无设备输出；没有输出本身不能证明参数错误。"
        ),
        device_path_text="设备未接入" if missing else f"当前 {view.device_path}",
        device_key=view.device_key,
        scan_summary=(
            f"现场扫描  USB {view.usb_ports} · 蓝牙 {view.bluetooth_ports} · "
            f"无稳定身份 {view.unidentified_ports}"
        ),
        agent_share_text=share_text,
        connection_copy=ConnectionCopy(
            address=address,
            address_label="复制人端地址",
            agent_text=share_text,
            agent_label="复制 Agent/MCP 说明",
        ),
        banner=banner,
        failures=_failure_cards(view),
        retry_hold=health.retry_hold,
        retry_listen=health.retry_listen,
    )


def _serial_format(params: SerialParams) -> str:
    """由实际配置生成 8N1 这类串口格式，不写死。"""
    return f"{params.data_bits}{params.parity}{int(params.stop_bits)}"


def _draft_serial_params(draft: Draft) -> SerialParams:
    """把草稿收成占口用的串口参数。"""
    return SerialParams(
        baudrate=draft.baud,
        data_bits=draft.data_bits,
        parity=draft.parity,
        stop_bits=draft.stop_bits,
        flow_control=draft.flow_control,
    )


def _default_create_draft(port: int, device_key: str = "", name: str = "") -> Draft:
    """新建线路的默认草稿：9600 8N1、无流控、GBK。"""
    return Draft(
        name=name,
        port=port,
        baud=9600,
        data_bits=8,
        parity="N",
        stop_bits=1,
        flow_control="none",
        decode="gbk",
        device_key=device_key,
    )


def _charset_label(decode: str) -> str:
    """Agent 字符集的展示名。"""
    return CHARSET_LABELS.get(decode, decode.upper())


def _line_display_name(name: str) -> str:
    """没有名称时仍给一条可辨认的线路标签。"""
    cleaned = name.strip()
    return cleaned if cleaned else "未命名线路"


def _format_note(params: SerialParams) -> str:
    """数据位、校验和停止位的中文读法。"""
    return (
        f"{params.data_bits} 数据位 · "
        f"{PARITY_LABELS.get(params.parity, params.parity)} · "
        f"{params.stop_bits} 停止位"
    )


def _format_preview(draft: Draft) -> str:
    """设置对话框里随改随变的串口格式说明。"""
    params = _draft_serial_params(draft)
    return f"串口格式 {_serial_format(params)} · {_format_note(params)}"


def _validate_draft(draft: Draft) -> FieldError | None:
    """检查端口、波特率和适配器支持的选项；非法则指出字段。"""
    if (
        not isinstance(draft.port, int)
        or draft.port < _PORT_MIN
        or draft.port > _PORT_MAX
    ):
        return FieldError(
            "port",
            f"请输入 {_PORT_MIN}–{_PORT_MAX} 之间的整数端口。",
            "配置尚未保存。",
        )
    if not isinstance(draft.baud, int) or draft.baud < 1:
        return FieldError("baud", "请输入正整数波特率。", "配置尚未保存。")
    if draft.data_bits not in ALLOWED_DATA_BITS:
        return FieldError("bits", "数据位不在适配器支持范围内。", "配置尚未保存。")
    if draft.parity not in ALLOWED_PARITY:
        return FieldError("parity", "校验方式不在适配器支持范围内。", "配置尚未保存。")
    if draft.stop_bits not in ALLOWED_STOP_BITS:
        return FieldError("stop", "停止位不在适配器支持范围内。", "配置尚未保存。")
    if draft.flow_control not in ALLOWED_FLOW:
        return FieldError("flow", "流控不在适配器支持范围内。", "配置尚未保存。")
    if draft.decode not in ALLOWED_CHARSETS:
        return FieldError("charset", "Agent 字符集不在支持范围内。", "配置尚未保存。")
    if len(draft.name.strip()) > _NAME_MAX:
        return FieldError(
            "lineName", f"线路名称最多 {_NAME_MAX} 个字。", "配置尚未保存。"
        )
    if not draft.device_key:
        return FieldError(
            "device",
            "请选择一台可用的 USB 或蓝牙串口。",
            "同一台设备只能分配给一条线路。",
        )
    return None


def _serial_changed(view: _LineView, draft: Draft) -> bool:
    """草稿是否改了会重开串口的参数。"""
    params = view.serial_params
    return (
        draft.baud != params.baudrate
        or draft.data_bits != params.data_bits
        or draft.parity != params.parity
        or draft.stop_bits != params.stop_bits
        or draft.flow_control != params.flow_control
    )


def _impact_text(
    view: _LineView | None,
    draft: Draft,
    *,
    creating: bool,
) -> Impact:
    """保存前说明会不会换入口、换设备或重新占口；多项同时改时都要说清。"""
    if creating or view is None:
        return Impact(
            "创建成功后，设备由串通占用。你可以复制地址连接 Telnet，或复制线路说明交给 Agent。",
            False,
            "创建线路",
        )
    port_change = draft.port != view.human_entry
    device_change = bool(draft.device_key) and draft.device_key != view.device_key
    params_change = _serial_changed(view, draft)
    if port_change:
        clients = (
            f"{view.human_clients} 个现有人端连接将断开；"
            if view.human_clients
            else "Telnet 书签需要更新；"
        )
        message = (
            f"保存后切换人端入口。{clients}Agent 后续需指名新端口。"
            "新端口不可用时，原线路与配置保留。"
        )
        if device_change:
            return Impact(
                f"{message} 设备绑定有变化：保存时会释放原设备并占用新设备，数据传输会短暂中断。",
                True,
                "保存并切换入口",
                True,
            )
        if params_change and view.hold == LineHold.WAITING:
            return Impact(
                f"{message} 串口参数也会保存，设备插回时按新参数占口。",
                True,
                "保存并切换入口",
                False,
            )
        if params_change:
            return Impact(
                f"{message} 串口参数有变化：保存时会重新占串口，数据传输会短暂中断。",
                True,
                "保存并切换入口",
                True,
            )
        return Impact(message, True, "保存并切换入口", False)
    if device_change:
        return Impact(
            "设备绑定有变化：保存时会释放原设备并占用新设备，数据传输会短暂中断。",
            True,
            "保存设置",
            True,
        )
    if params_change:
        if view.hold == LineHold.WAITING:
            return Impact(
                "设备未接入：先保存设置，设备插回时按新参数占口。",
                False,
                "保存设置",
                False,
            )
        return Impact(
            "串口参数有变化：保存时会重新占串口，数据传输会短暂中断。",
            True,
            "保存设置",
            True,
        )
    return Impact(
        "仅修改名称或 Agent 字符集时，不重新打开串口，已有连接保持。",
        False,
        "保存设置",
        False,
    )


def _ignored_port_note(*, unidentified_ports: int) -> str:
    """说明现场有哪些串口因没有稳定身份而被忽略。"""
    if unidentified_ports <= 0:
        return ""
    return f"现场另有 {unidentified_ports} 个缺少稳定身份的串口，未纳入线路。"


def _waiting_reason(unidentified_ports: int) -> str:
    """等待设备时的原因说明；现场有被忽略串口时一并指出。"""
    reason = "线路还在，但这台设备此刻不在现场。"
    note = _ignored_port_note(unidentified_ports=unidentified_ports)
    return f"{reason}{note}" if note else reason


def _line_health(view: _LineView) -> _LineHealth:
    """设备、人端监听、客户端分开呈现。"""
    if not view.human_listening:
        human = "人端：未监听"
        human_class = "error-color"
        badge = "端口冲突"
        badge_class = "error-color"
    else:
        human = "人端：正在监听"
        human_class = ""
        badge = "占口"
        badge_class = ""
    if view.hold == LineHold.WAITING:
        device = "设备：未接入"
        device_class = "waiting"
        if view.human_listening:
            badge = "等待设备"
            badge_class = "waiting"
    elif view.hold == LineHold.CONFLICT:
        device = "设备：占用冲突"
        device_class = "error-color"
        if view.human_listening:
            badge = "占用冲突"
            badge_class = "error-color"
    else:
        device = "设备：已占口"
        device_class = ""
    writable = view.hold == LineHold.HELD
    if writable and view.human_listening:
        rw_label = "可读写"
    elif writable:
        rw_label = "设备可写 · 人端未监听"
    else:
        rw_label = "不可写"
    agent = "Agent 已连接" if view.agent_connected else "Agent 未连接"
    clients = f"人端 {view.human_clients} · {agent}"
    return _LineHealth(
        writable=writable,
        rw_label=rw_label,
        badge=badge,
        badge_class=badge_class,
        device=device,
        device_class=device_class,
        human=human,
        human_class=human_class,
        clients=clients,
        retry_hold=view.hold == LineHold.CONFLICT,
        retry_listen=not view.human_listening,
    )


def _rw_class(writable: bool, listening: bool) -> str:
    """可读写用正常色，不可写用错误色，人端未监听但设备可写用等待色。"""
    if writable and listening:
        return ""
    if writable:
        return "waiting"
    return "error-color"


def _failure_cards(view: _LineView) -> tuple[FailureCard, ...]:
    """当前失败状态的原因、下一步和恢复动作。"""
    notices: list[FailureCard] = []
    if not view.human_listening:
        notices.append(
            FailureCard(
                kind="port",
                title=f"人端入口 {view.human_entry} 端口冲突",
                reason="人端入口绑不上：本机端口已被占用。",
                next_action=(
                    "请关闭占用这个端口的程序，然后点「重试监听」；"
                    "或在线路设置里换一个入口。"
                ),
                action="retry_listen",
                action_label="重试监听",
                severity="error",
            )
        )
    if view.hold == LineHold.WAITING:
        notices.append(
            FailureCard(
                kind="waiting",
                title="等待设备重新接入",
                reason=_waiting_reason(view.unidentified_ports),
                next_action=(
                    "让同一 USB 或蓝牙串口重新出现。人端不用断开，"
                    "写入现在不会发送，恢复后也不会补发。"
                ),
                action="",
                action_label="",
                severity="waiting",
            )
        )
    if view.hold == LineHold.CONFLICT:
        path = view.device_path or "该串口"
        notices.append(
            FailureCard(
                kind="conflict",
                title=f"{path} 正被其他程序占用",
                reason="设备在场，但被其他程序占用，串通占不到口。",
                next_action="请关闭直接打开这个串口的软件，然后点「重试占口」。",
                action="retry_hold",
                action_label="重试占口",
                severity="error",
            )
        )
    return tuple(notices)


def _recovery_notice(
    previous: _LineView,
    current: _LineView,
) -> tuple[str, str] | None:
    """设备插回、占用解除或入口恢复监听时给一句反馈。"""
    recovered_hold = previous.hold != LineHold.HELD and current.hold == LineHold.HELD
    recovered_listen = (not previous.human_listening) and current.human_listening
    if recovered_hold and previous.hold == LineHold.WAITING:
        title = "设备已插回并占口"
        message = (
            "同一 USB 或蓝牙身份已对上。现在可以继续读写；断线期间的写入没有补发。"
        )
    elif recovered_hold and previous.hold == LineHold.CONFLICT:
        title = "占用冲突已解除"
        message = (
            "对方已放口，线路已重新占口。现在可以继续读写；冲突期间的写入没有补发。"
        )
    elif recovered_listen:
        title = "人端入口已恢复监听"
        message = f"Telnet 可以再次接入 {_listen_address(current.human_entry)}。"
    else:
        return None
    if recovered_hold and recovered_listen and previous.hold != LineHold.WAITING:
        message = f"{message} 人端入口也已恢复监听。"
    elif recovered_hold and recovered_listen:
        message = f"{message} 人端入口同时恢复监听。"
    return title, message


def _agent_share_text(view: _LineView) -> str:
    """复制给已接入串通的 Agent 的线路与 MCP 连接说明。"""
    name = f"（线路名称：{view.name}）" if view.name else ""
    params = view.serial_params
    return (
        f"请通过串通访问人端入口 {view.human_entry}{name}。\n"
        f"Cursor 里用 MCP：{_MCP_COMMAND}。"
        f"Agent 端是本机命名管道 {_AGENT_PIPE}，不是 TCP；"
        "MCP 只做翻译，自己不打开设备。\n"
        f"先用 list_lines 核对线路状态，再按需调用 read_line / write_line，"
        f"必须指名 {view.human_entry}。\n"
        "不要直接打开 COM，不要创建、修改或拆掉线路，也不要修改串口参数。\n"
        f"当前参数：{params.baudrate} {_serial_format(params)}，"
        f"{FLOW_LABELS.get(params.flow_control, params.flow_control)}；"
        f"Agent 字符集 {_charset_label(view.decode)}。"
    )


def _suggest_port(used: set[int], start: int = 2222) -> int:
    """给出一个尚未被线路占用的人端入口。"""
    port = start
    while port in used and port <= _PORT_MAX:
        port += 1
    if port > _PORT_MAX:
        return start
    return port


def _identity_key(identity: SerialIdentity) -> str:
    """下拉框用的身份键，不是 COM 路径。"""
    if isinstance(identity, BluetoothIdentity):
        return f"BT|{identity.hwid}"
    return f"{identity.vid:04X}:{identity.pid:04X}|{identity.serial}"


def _usb_identity_text(identity: UsbIdentity) -> str:
    """稳定 USB 身份的展示：VID:PID 与序列号。"""
    vid_pid = f"{identity.vid:04X}:{identity.pid:04X}"
    serial = identity.serial.strip()
    if serial:
        return f"{vid_pid} · 序列号 {serial}"
    return vid_pid


def _bluetooth_identity_text(identity: BluetoothIdentity) -> str:
    """展示蓝牙硬件标识里的远端地址和服务实例。"""
    tail = identity.hwid.rsplit("\\", 1)[-1]
    address_part, _, instance = tail.partition("_")
    address = address_part.rsplit("&", 1)[-1]
    if len(address) == 12 and all(char in "0123456789ABCDEF" for char in address):
        shown_address = ":".join(
            address[index : index + 2] for index in range(0, len(address), 2)
        )
        suffix = f" · 实例 {instance}" if instance else ""
        return f"地址 {shown_address}{suffix}"
    return f"硬件标识 {tail}"


def _device_option_label(path: str, identity: SerialIdentity) -> str:
    """设备选项同时给出当前 COM 路径和稳定设备身份。"""
    shown = path.strip() or "未接入"
    if isinstance(identity, BluetoothIdentity):
        return f"{shown} · 蓝牙 {_bluetooth_identity_text(identity)}"
    return f"{shown} · USB {_usb_identity_text(identity)}"


def _empty_device_hint(
    *,
    present: int,
    available: int,
    unidentified_ports: int = 0,
) -> DeviceHint | None:
    """打开创建流程时，没有可选设备就给出可行动提示。"""
    if available > 0:
        return None
    if present > 0:
        return DeviceHint(
            "没有可分配的串口设备",
            "现场的 USB 或蓝牙串口都已分配给其他线路。请先拆掉一条线路，或再配对另一台设备。",
            "rescan",
            "重新扫描设备",
        )
    note = _ignored_port_note(unidentified_ports=unidentified_ports)
    detail = (
        f"{note}请插入带稳定序列号的 USB 转接器，或配对蓝牙串口，"
        "然后点「重新扫描设备」。"
        if note
        else "现场没有可用的串口设备。请插入带稳定序列号的 USB 转接器，"
        "或配对蓝牙串口，然后点「重新扫描设备」。"
    )
    return DeviceHint(
        "没有可用的串口设备",
        detail,
        "rescan",
        "重新扫描设备",
    )


def _create_device_choices(
    paths: Mapping[SerialIdentity, str],
    assigned: set[SerialIdentity],
    *,
    current: SerialIdentity | None = None,
    current_path: str = "",
    unidentified_ports: int = 0,
) -> _DeviceChoice:
    """创建设备下拉：过滤已分配；编辑时保留当前绑定并列出可切换设备。"""
    if current is not None:
        current_key = _identity_key(current)
        path = current_path or "未接入"
        options: dict[str, str] = {current_key: _device_option_label(path, current)}
        for identity, present_path in paths.items():
            if identity == current or identity in assigned:
                continue
            options[_identity_key(identity)] = _device_option_label(
                present_path, identity
            )
        return _DeviceChoice(options, current_key, None)
    options = {}
    default: str | None = None
    for identity, path in paths.items():
        if identity in assigned:
            continue
        key = _identity_key(identity)
        options[key] = _device_option_label(path, identity)
        if default is None:
            default = key
    return _DeviceChoice(
        options,
        default,
        _empty_device_hint(
            present=len(paths),
            available=len(options),
            unidentified_ports=unidentified_ports,
        ),
    )


def _parse_identity_key(text: str) -> SerialIdentity:
    """从身份键还原 USB 或蓝牙身份。"""
    if text.startswith("BT|"):
        return BluetoothIdentity(hwid=text[3:])
    vid_pid, serial = text.split("|", 1)
    vid_s, pid_s = vid_pid.split(":", 1)
    return UsbIdentity(vid=int(vid_s, 16), pid=int(pid_s, 16), serial=serial)


def _listen_address(port: int) -> str:
    """人端 Telnet 地址。"""
    return f"127.0.0.1:{port}"


def _format_bytes(count: int) -> str:
    """收发计数用等宽数字，避免跳变。"""
    return f"{count:,} B"


def _format_last_rx(last_rx_at: float | None, *, missing: bool) -> str:
    """最近收到设备数据的展示；没有输出本身不能证明参数错误。"""
    if last_rx_at is None:
        return "尚未收到"
    stamp = time.strftime("%H:%M:%S", time.localtime(last_rx_at))
    if missing:
        return f"断开前 {stamp}"
    return stamp
