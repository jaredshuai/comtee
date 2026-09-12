"""线路设置的可测层：校验、串口格式、状态文案和保存影响。"""

import time
from dataclasses import dataclass

from comtee.hub import LineHold, LineStatus, SerialParams, UsbIdentity

ALLOWED_DATA_BITS = (5, 6, 7, 8)
ALLOWED_PARITY = ("N", "E", "O")
ALLOWED_STOP_BITS = (1, 2)
ALLOWED_FLOW = ("none", "rtscts", "xonxoff", "dsrdtr")
ALLOWED_CHARSETS = ("gbk", "utf-8")
BAUD_PRESETS = (9600, 19200, 38400, 57600, 115200)
NAME_MAX = 32
PORT_MIN = 1
PORT_MAX = 65535

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
class LineView:
    """给面板用的线路只读视图，不含字节流。"""

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


@dataclass(frozen=True)
class FieldError:
    """某一字段的就地错误。"""

    field: str
    title: str
    message: str


@dataclass(frozen=True)
class Impact:
    """保存前要告诉人的影响。"""

    message: str
    warning: bool
    submit_label: str


@dataclass(frozen=True)
class SplitStatus:
    """人端监听和设备占口分开后的文案。"""

    badge: str
    badge_class: str
    human: str
    device: str
    human_class: str
    device_class: str


@dataclass(frozen=True)
class LineHealth:
    """列表和详情共用的分项状态：设备、人端、客户端和可否读写。"""

    writable: bool
    rw_label: str
    badge: str
    badge_class: str
    device: str
    device_class: str
    human: str
    human_class: str
    clients: str
    reason: str
    next_action: str
    retry_hold: bool
    retry_listen: bool


@dataclass(frozen=True)
class StatusNotice:
    """一个失败状态的原因、下一步和可选恢复动作。"""

    kind: str
    title: str
    reason: str
    next_action: str
    action: str
    action_label: str
    severity: str


@dataclass(frozen=True)
class RecoveryNotice:
    """状态好转时给面板的一句反馈。"""

    title: str
    message: str


def serial_format(params: SerialParams) -> str:
    """由实际配置生成 8N1 这类串口格式，不写死。"""
    return f"{params.data_bits}{params.parity}{int(params.stop_bits)}"


def draft_serial_params(draft: Draft) -> SerialParams:
    """把草稿收成占口用的串口参数。"""
    return SerialParams(
        baudrate=draft.baud,
        data_bits=draft.data_bits,
        parity=draft.parity,
        stop_bits=draft.stop_bits,
        flow_control=draft.flow_control,
    )


def charset_label(decode: str) -> str:
    """Agent 字符集的展示名。"""
    return CHARSET_LABELS.get(decode, decode.upper())


def format_preview(draft: Draft) -> str:
    """设置对话框里随改随变的串口格式说明。"""
    params = draft_serial_params(draft)
    return (
        f"串口格式 {serial_format(params)} · {params.data_bits} 数据位 · "
        f"{PARITY_LABELS.get(params.parity, params.parity)} · {params.stop_bits} 停止位"
    )


def validate_draft(draft: Draft) -> FieldError | None:
    """检查端口、波特率和适配器支持的选项；非法则指出字段。"""
    if (
        not isinstance(draft.port, int)
        or draft.port < PORT_MIN
        or draft.port > PORT_MAX
    ):
        return FieldError(
            "port",
            f"请输入 {PORT_MIN}–{PORT_MAX} 之间的整数端口。",
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
    if len(draft.name.strip()) > NAME_MAX:
        return FieldError(
            "lineName", f"线路名称最多 {NAME_MAX} 个字。", "配置尚未保存。"
        )
    if not draft.device_key:
        return FieldError(
            "device", "请选择一台可用的 USB 设备。", "同一台设备只能分配给一条线路。"
        )
    return None


def serial_changed(view: LineView, draft: Draft) -> bool:
    """草稿是否改了会重开串口的参数。"""
    params = view.serial_params
    return (
        draft.baud != params.baudrate
        or draft.data_bits != params.data_bits
        or draft.parity != params.parity
        or draft.stop_bits != params.stop_bits
        or draft.flow_control != params.flow_control
    )


def impact_text(view: LineView | None, draft: Draft, *, creating: bool) -> Impact:
    """保存前说明会不会换入口、会不会短暂中断串口。"""
    if creating or view is None:
        return Impact(
            "创建成功后，设备由串通占用。你可以复制地址连接 Telnet，或复制线路说明交给 Agent。",
            False,
            "创建线路",
        )
    port_change = draft.port != view.human_entry
    params_change = serial_changed(view, draft)
    if port_change:
        clients = (
            f"{view.human_clients} 个现有人端连接将断开；"
            if view.human_clients
            else "Telnet 书签需要更新；"
        )
        return Impact(
            f"保存后切换人端入口。{clients}Agent 后续需指名新端口。新端口不可用时，原线路与配置保留。",
            True,
            "保存并切换入口",
        )
    if params_change:
        if view.hold == LineHold.WAITING:
            message = "设备未接入：先保存设置，设备插回时按新参数占口。"
        else:
            message = "串口参数有变化：保存时会重新占串口，数据传输会短暂中断。"
        return Impact(message, view.hold == LineHold.HELD, "保存设置")
    return Impact(
        "仅修改名称或 Agent 字符集时，不重新打开串口，已有连接保持。",
        False,
        "保存设置",
    )


def line_health(view: LineView) -> LineHealth:
    """设备、人端监听、客户端分开呈现；失败时给出原因和下一步。"""
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
    reason = ""
    next_action = ""
    if not view.human_listening:
        reason = "人端入口绑不上：本机端口已被占用。"
        next_action = (
            "请关闭占用这个端口的程序，然后点「重试监听」；或在线路设置里换一个入口。"
        )
    elif view.hold == LineHold.WAITING:
        reason = "线路还在，但这台设备此刻不在现场。"
        next_action = (
            "插回同一 USB 转接器。人端不用断开，写入现在不会发送，恢复后也不会补发。"
        )
    elif view.hold == LineHold.CONFLICT:
        reason = "设备在场，但被其他程序占用，串通占不到口。"
        next_action = "请关闭直接打开这个串口的软件，然后点「重试占口」。"
    return LineHealth(
        writable=writable,
        rw_label=rw_label,
        badge=badge,
        badge_class=badge_class,
        device=device,
        device_class=device_class,
        human=human,
        human_class=human_class,
        clients=clients,
        reason=reason,
        next_action=next_action,
        retry_hold=view.hold == LineHold.CONFLICT,
        retry_listen=not view.human_listening,
    )


def split_status(view: LineView) -> SplitStatus:
    """人端监听和设备占口分开呈现；总徽章取更严重的那头。"""
    health = line_health(view)
    return SplitStatus(
        health.badge,
        health.badge_class,
        health.human,
        health.device,
        health.human_class,
        health.device_class,
    )


def failure_notices(view: LineView) -> tuple[StatusNotice, ...]:
    """当前失败状态的原因、下一步和恢复动作。"""
    notices: list[StatusNotice] = []
    if not view.human_listening:
        notices.append(
            StatusNotice(
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
            StatusNotice(
                kind="waiting",
                title="等待设备重新接入",
                reason="线路还在，但这台设备此刻不在现场。",
                next_action=(
                    "插回同一 USB 转接器。人端不用断开，"
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
            StatusNotice(
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


def recovery_notice(previous: LineView, current: LineView) -> RecoveryNotice | None:
    """设备插回、占用解除或入口恢复监听时给一句反馈。"""
    recovered_hold = previous.hold != LineHold.HELD and current.hold == LineHold.HELD
    recovered_listen = (not previous.human_listening) and current.human_listening
    if recovered_hold and previous.hold == LineHold.WAITING:
        title = "设备已插回并占口"
        message = "同一 USB 身份已对上。现在可以继续读写；断线期间的写入没有补发。"
    elif recovered_hold and previous.hold == LineHold.CONFLICT:
        title = "占用冲突已解除"
        message = (
            "对方已放口，线路已重新占口。现在可以继续读写；冲突期间的写入没有补发。"
        )
    elif recovered_listen:
        title = "人端入口已恢复监听"
        message = f"Telnet 可以再次接入 {listen_address(current.human_entry)}。"
    else:
        return None
    if recovered_hold and recovered_listen and previous.hold != LineHold.WAITING:
        message = f"{message} 人端入口也已恢复监听。"
    elif recovered_hold and recovered_listen:
        message = f"{message} 人端入口同时恢复监听。"
    return RecoveryNotice(title, message)


def agent_share_text(view: LineView) -> str:
    """复制给已接入串通的 Agent 的线路说明。"""
    name = f"（线路名称：{view.name}）" if view.name else ""
    params = view.serial_params
    return (
        f"请通过串通访问人端入口 {view.human_entry}{name}。\n"
        f"先用 list_lines 核对线路状态，再按需调用 read_line / write_line，必须指名 {view.human_entry}。\n"
        "不要直接打开 COM，不要创建、修改或拆掉线路，也不要修改串口参数。\n"
        f"当前参数：{params.baudrate} {serial_format(params)}，"
        f"{FLOW_LABELS.get(params.flow_control, params.flow_control)}；"
        f"Agent 字符集 {charset_label(view.decode)}。"
    )


def suggest_port(used: set[int], start: int = 2222) -> int:
    """给出一个尚未被线路占用的人端入口。"""
    port = start
    while port in used and port <= PORT_MAX:
        port += 1
    if port > PORT_MAX:
        return start
    return port


def identity_key(identity: UsbIdentity) -> str:
    """下拉框用的身份键，不是 COM 路径。"""
    return f"{identity.vid:04X}:{identity.pid:04X}|{identity.serial}"


def parse_identity_key(text: str) -> UsbIdentity:
    """从身份键还原 USB 身份。"""
    vid_pid, serial = text.split("|", 1)
    vid_s, pid_s = vid_pid.split(":", 1)
    return UsbIdentity(vid=int(vid_s, 16), pid=int(pid_s, 16), serial=serial)


def status_to_view(line: LineStatus, path: str) -> LineView:
    """把串通状态收成面板视图。"""
    return LineView(
        human_entry=line.human_entry,
        name=line.name,
        hold=line.hold,
        human_listening=line.human_listening,
        human_clients=line.human_clients,
        agent_connected=line.agent_connected,
        serial_params=line.serial_params,
        decode=line.decode,
        device_key=identity_key(line.device),
        device_path=path,
    )


def listen_address(port: int) -> str:
    """人端 Telnet 地址。"""
    return f"127.0.0.1:{port}"


def format_bytes(count: int) -> str:
    """收发计数用等宽数字，避免跳变。"""
    return f"{count:,} B"


def format_last_rx(last_rx_at: float | None, *, missing: bool) -> str:
    """最近收到设备数据的展示；没有输出本身不能证明参数错误。"""
    if last_rx_at is None:
        return "尚未收到"
    stamp = time.strftime("%H:%M:%S", time.localtime(last_rx_at))
    if missing:
        return f"断开前 {stamp}"
    return stamp
