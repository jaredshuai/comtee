"""串通：人端入口与设备一对一编排，线路在则占口。"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

_RECENT_LIMIT = 4096


class ArrangementRejected(Exception):
    """两条线路不得共享同一人端入口或同一台设备。"""


class HumanEntryOccupied(Exception):
    """人端入口绑不上：本机端口已被占用。"""

    def __init__(self, human_entry: int) -> None:
        """记下冲突的人端入口。"""
        self.human_entry = human_entry
        super().__init__(f"人端入口 {human_entry} 被其他程序占用")


class SerialApplyFailed(Exception):
    """新串口参数未能应用到设备，原参数已保留。"""

    def __init__(self, message: str = "新串口参数未能应用，原配置已保留") -> None:
        """带上给面板看的原因。"""
        super().__init__(message)


class AgentForbidden(Exception):
    """Agent 不能编排线路，也不能改串口参数和解码。"""


class LineHold(StrEnum):
    """线路对设备的占口结果。"""

    HELD = "占口"
    WAITING = "等待设备"
    CONFLICT = "占用冲突"


@dataclass(frozen=True)
class UsbIdentity:
    """用 VID:PID 与序列号辨认的一台 USB 设备。"""

    vid: int
    pid: int
    serial: str

    def key(self) -> str:
        """稳定的选项身份键，不随 COM 号改变。"""
        return f"{self.vid:04X}:{self.pid:04X}|{self.serial}"

    def label(self) -> str:
        """面向操作员的稳定 USB 身份展示。"""
        vid_pid = f"{self.vid:04X}:{self.pid:04X}"
        serial = self.serial.strip()
        if serial:
            return f"USB {vid_pid} · 序列号 {serial}"
        return f"USB {vid_pid}"

    def to_dict(self) -> dict[str, object]:
        """结构化字典，给编排存档和 Agent 视图共用。"""
        return {
            "device_type": "usb",
            "vid": self.vid,
            "pid": self.pid,
            "serial": self.serial,
        }


@dataclass(frozen=True)
class BluetoothIdentity:
    """用 Windows BTHENUM 硬件标识辨认的一台蓝牙串口设备。"""

    hwid: str

    def __post_init__(self) -> None:
        """统一去空白并转大写，避免同一蓝牙身份大小写不一致导致失配。"""
        object.__setattr__(self, "hwid", self.hwid.strip().upper())

    def key(self) -> str:
        """稳定的选项身份键，不随 COM 号改变。"""
        return f"BT|{self.hwid}"

    def label(self) -> str:
        """展示蓝牙硬件标识里的远端地址和服务实例。"""
        tail = self.hwid.rsplit("\\", 1)[-1]
        address_part, _, instance = tail.partition("_")
        address = address_part.rsplit("&", 1)[-1]
        if len(address) == 12 and all(char in "0123456789ABCDEF" for char in address):
            shown_address = ":".join(
                address[index : index + 2] for index in range(0, len(address), 2)
            )
            suffix = f" · 实例 {instance}" if instance else ""
            return f"蓝牙 地址 {shown_address}{suffix}"
        return f"蓝牙 硬件标识 {tail}"

    def to_dict(self) -> dict[str, object]:
        """结构化字典，给编排存档和 Agent 视图共用。"""
        return {
            "device_type": "bluetooth",
            "hwid": self.hwid,
        }


SerialIdentity = UsbIdentity | BluetoothIdentity


def parse_identity_key(text: str) -> SerialIdentity:
    """从选项身份键还原 USB 或蓝牙设备身份。"""
    if text.startswith("BT|"):
        hwid = text[3:].strip()
        if not hwid:
            raise ValueError(f"无效的蓝牙身份键: {text}")
        return BluetoothIdentity(hwid=hwid)
    if "|" not in text:
        raise ValueError(f"无效的设备身份键: {text}")
    vid_pid, serial = text.split("|", 1)
    if ":" not in vid_pid:
        raise ValueError(f"无效的 USB 身份键: {text}")
    vid_s, pid_s = vid_pid.split(":", 1)
    return UsbIdentity(vid=int(vid_s, 16), pid=int(pid_s, 16), serial=serial)


def identity_from_dict(data: Mapping[str, object]) -> SerialIdentity:
    """从存档字典恢复设备身份；兼容无 device_type 的旧 USB 记录。"""
    device_type = str(data.get("device_type", "usb"))
    if device_type == "bluetooth":
        return BluetoothIdentity(hwid=str(data["hwid"]))
    if device_type == "usb":
        return UsbIdentity(
            vid=int(str(data["vid"])),
            pid=int(str(data["pid"])),
            serial=str(data["serial"]),
        )
    raise ValueError(f"不支持的设备类型: {device_type}")


@dataclass(frozen=True)
class SerialParams:
    """占口时用的串口参数，默认 9600 8N1 无流控。"""

    baudrate: int = 9600
    data_bits: int = 8
    parity: str = "N"
    stop_bits: int = 1
    flow_control: str = "none"


@dataclass(frozen=True)
class LineStatus:
    """一条线路对外可见的编排与占口状态。"""

    human_entry: int
    device: SerialIdentity
    serial_params: SerialParams
    decode: str
    hold: LineHold
    human_clients: int
    agent_connected: bool
    name: str = ""
    human_listening: bool = True
    rx_bytes: int = 0
    tx_bytes: int = 0
    last_rx_at: float | None = None


@dataclass(frozen=True)
class LineArrangement:
    """需要写盘并在启动时恢复的线路编排，不含占口结果。"""

    human_entry: int
    device: SerialIdentity
    serial_params: SerialParams
    decode: str
    name: str = ""


@dataclass(frozen=True)
class SerialScan:
    """一次串口枚举的结果：可用身份及其余被忽略的串口数量。"""

    paths: dict[SerialIdentity, str]
    usb: int = 0
    bluetooth: int = 0
    unidentified: int = 0

    @property
    def total(self) -> int:
        """本次枚举看到的全部串口数量。"""
        return self.usb + self.bluetooth + self.unidentified


@dataclass(frozen=True)
class WriteResult:
    """Agent 端按文本写入线路的结果。"""

    ok: bool
    error: str = ""


@dataclass(frozen=True)
class AgentReadResult:
    """Agent 端按文本读取线路的结果。"""

    ok: bool
    text: str = ""
    error: str = ""


class SerialPort(Protocol):
    """按稳定设备身份占口、放口的串口适配器。"""

    def occupy(self, device: SerialIdentity, params: SerialParams) -> LineHold:
        """打开并独占该设备；打不开则占用冲突，不在则等待设备。"""
        ...

    def release(self, device: SerialIdentity) -> None:
        """放掉该设备。"""
        ...

    def listen(self, device: SerialIdentity, on_bytes: Callable[[bytes], None]) -> None:
        """设备上来的原字节回调给串通。"""
        ...

    def write(self, device: SerialIdentity, data: bytes) -> None:
        """把客户端写下的原字节打进设备。"""
        ...

    def scan(self) -> SerialScan:
        """枚举此刻现场插着的可支持串口与路径。"""
        ...

    def watch(self, on_change: Callable[[], None]) -> None:
        """插拔变化时通知串通去对照现场。"""
        ...


class ArrangementStore(Protocol):
    """线路编排的持久存档。"""

    def load(self) -> tuple[LineArrangement, ...]:
        """读出上一份编排。"""
        ...

    def save(self, lines: tuple[LineArrangement, ...]) -> None:
        """写入当前编排。"""
        ...


class HumanListener(Protocol):
    """在本机回环上听人端入口。"""

    def attach(self, on_connect: Callable[[int], Client]) -> None:
        """接到串通客户端挂接回调。"""
        ...

    def occupy(self, human_entry: int) -> bool:
        """开始听该人端入口；听成了为 True。"""
        ...

    def release(self, human_entry: int) -> None:
        """停掉该人端入口。"""
        ...


@dataclass
class _Line:
    """一条线路的内部记录。"""

    human_entry: int
    device: SerialIdentity
    serial_params: SerialParams = field(default_factory=SerialParams)
    decode: str = "gbk"
    name: str = ""
    hold: LineHold = LineHold.WAITING
    human_listening: bool = True
    clients: list[_Endpoint] = field(default_factory=list)
    recent: bytearray = field(default_factory=bytearray)
    rx_bytes: int = 0
    tx_bytes: int = 0
    last_rx_at: float | None = None


class _Endpoint:
    """客户端与 Agent 端共用的线路缓冲与离开基座。"""

    def __init__(self, hub: Comtee, human_entry: int) -> None:
        """绑定到串通上的一条线路。"""
        self._hub = hub
        self._human_entry = human_entry
        self._inbox = bytearray()

    @property
    def human_entry(self) -> int:
        """此刻这条客户端挂着的人端入口。"""
        return self._human_entry

    def write(self, data: bytes) -> bool:
        """写下原字节：只有进设备才算成功，并扇出到同线路其他客户端。"""
        return self._hub._write_from_client(self, data)

    def leave(self) -> None:
        """离开线路，不再收到后续字节。"""
        self._hub._detach_client(self)

    def _deliver(self, data: bytes) -> None:
        """收下扇出到本客户端的原字节。"""
        self._inbox.extend(data)


class Client(_Endpoint):
    """挂在某条线路上的人端，收发明文原字节。"""

    def received(self) -> bytes:
        """取出尚未取走的、扇出到本客户端的原字节。"""
        data = bytes(self._inbox)
        self._inbox.clear()
        return data


class Agent(_Endpoint):
    """挂在已有线路上的 Agent 端：读写均按线路解码收发文本。"""

    def received(self) -> str:
        """取出尚未取走的可读字，按该线路解码。"""
        raw = bytes(self._inbox)
        self._inbox.clear()
        return raw.decode(self._hub._decode_of(self._human_entry), errors="replace")

    def write_text(self, text: str) -> WriteResult:
        """按线路解码把文本编成原字节写入设备，返回明确成败原因。"""
        return self._hub._write_text_from_agent(self, text)

    def create_line(self, *_args: object, **_kwargs: object) -> None:
        """拒绝：Agent 不能创建线路。"""
        raise AgentForbidden("Agent 不能编排线路")

    def change_line(self, **_kwargs: object) -> None:
        """拒绝：Agent 不能改串口参数或解码。"""
        raise AgentForbidden("Agent 不能改串口参数和解码")

    def remove_line(self, *_args: object, **_kwargs: object) -> None:
        """拒绝：Agent 不能拆线路。"""
        raise AgentForbidden("Agent 不能编排线路")


class AgentSession:
    """Agent 端多线路视图：管理指名挂接、双向解码读写与端口迁移跟随。"""

    def __init__(self, hub: Comtee) -> None:
        """绑定串通；进场前不占设备、不挂线路。"""
        self._hub = hub
        self._agents: dict[int, Agent] = {}

    def list_lines(self) -> tuple[LineStatus, ...]:
        """列出当前全部线路状态，不含设备字节。"""
        return self._hub.list_lines()

    def read(self, human_entry: int) -> AgentReadResult:
        """指名读取该线路解码后的最近与新到文本。"""
        try:
            return AgentReadResult(ok=True, text=self._agent(human_entry).received())
        except KeyError:
            return AgentReadResult(ok=False, error="没有这条线路")

    def write(self, human_entry: int, text: str) -> WriteResult:
        """指名写入文本并按线路解码发进设备；未占口时明确失败且不排队。"""
        try:
            return self._agent(human_entry).write_text(text)
        except KeyError:
            return WriteResult(ok=False, error="没有这条线路")

    def close(self) -> None:
        """Agent 离开所有已挂线路；不放口、不拆编排。"""
        for agent in self._agents.values():
            agent.leave()
        self._agents.clear()

    def _agent(self, human_entry: int) -> Agent:
        """按人端入口取已挂 Agent；入口迁移或线路拆除后自动同步。"""
        remapped: dict[int, Agent] = {}
        for agent in self._agents.values():
            if self._hub._agent_attached(agent):
                remapped[agent.human_entry] = agent
            else:
                agent.leave()
        self._agents = remapped
        if not self._hub._has_line(human_entry):
            raise KeyError(human_entry)
        existing = self._agents.get(human_entry)
        if existing is not None:
            return existing
        agent = self._hub.attach_agent(human_entry)
        self._agents[human_entry] = agent
        return agent


class Comtee:
    """串通模块：编排线路、列出状态；占口与恢复藏在实现里。"""

    def __init__(
        self,
        serial: SerialPort,
        store: ArrangementStore,
        human: HumanListener | None = None,
    ) -> None:
        """注入串口、编排存档；人端入口可选。"""
        self._serial = serial
        self._store = store
        self._human = human
        self._lines: dict[int, _Line] = {}
        if human is not None:
            human.attach(self.attach_client)
        self._serial.watch(self._reconcile)
        self._last_scan: SerialScan = self._serial.scan()
        self._restore()

    def create_line(
        self,
        human_entry: int,
        device: SerialIdentity,
        *,
        name: str = "",
        serial_params: SerialParams | None = None,
        decode: str = "gbk",
    ) -> None:
        """创建一对一线路并占口；入口绑不上则整笔回滚。"""
        if human_entry in self._lines:
            raise ArrangementRejected("人端入口已被另一条线路占用")
        if any(line.device == device for line in self._lines.values()):
            raise ArrangementRejected("设备已被另一条线路占用")
        params = serial_params if serial_params is not None else SerialParams()
        if self._human is not None and not self._human.occupy(human_entry):
            raise HumanEntryOccupied(human_entry)
        try:
            self._install(
                LineArrangement(
                    human_entry=human_entry,
                    device=device,
                    serial_params=params,
                    decode=decode,
                    name=_clean_name(name),
                ),
                bind_entry=False,
                human_listening=True,
            )
        except Exception:
            if self._human is not None:
                self._human.release(human_entry)
            raise
        self._persist()

    def list_lines(self) -> tuple[LineStatus, ...]:
        """列出当前全部线路状态。"""
        return tuple(self._status(line) for line in self._lines.values())

    def attach_client(self, human_entry: int) -> Client:
        """把一个客户端挂上已有线路。"""
        client = Client(self, human_entry)
        self._lines[human_entry].clients.append(client)
        return client

    def attach_agent(self, human_entry: int) -> Agent:
        """把 Agent 挂上指名的已有线路，进场带最近缓冲。"""
        line = self._lines[human_entry]
        agent = Agent(self, human_entry)
        if line.recent:
            agent._deliver(bytes(line.recent))
        line.clients.append(agent)
        return agent

    def change_line(
        self,
        human_entry: int,
        *,
        new_entry: int | None = None,
        device: SerialIdentity | None = None,
        name: str | None = None,
        serial_params: SerialParams | None = None,
        decode: str | None = None,
    ) -> None:
        """改一条线路的入口、设备、名称、串口参数和/或解码。"""
        line = self._lines[human_entry]
        device_changed = device is not None and device != line.device
        if device_changed and any(
            other is not line and other.device == device
            for other in self._lines.values()
        ):
            raise ArrangementRejected("同一台设备不能分配给两条线路")
        pending_entry: int | None = None
        if new_entry is not None and new_entry != human_entry:
            if new_entry in self._lines:
                raise ArrangementRejected("人端入口已被另一条线路占用")
            if self._human is not None and not self._human.occupy(new_entry):
                raise HumanEntryOccupied(new_entry)
            pending_entry = new_entry
        try:
            target_params = (
                serial_params if serial_params is not None else line.serial_params
            )
            if device_changed:
                assert device is not None
                self._reoccupy(
                    line,
                    device,
                    target_params,
                    conflict_message="新设备正被其他程序占用，原设备绑定已保留",
                )
            elif serial_params is not None and serial_params != line.serial_params:
                self._reoccupy(
                    line,
                    line.device,
                    target_params,
                    conflict_message="新串口参数未能应用，原配置已保留",
                )
            if decode is not None:
                line.decode = decode
            if name is not None:
                line.name = _clean_name(name)
            if pending_entry is not None:
                self._rekey_entry(line, pending_entry)
        except Exception:
            if pending_entry is not None and self._human is not None:
                self._human.release(pending_entry)
            raise
        self._persist()

    def remove_line(self, human_entry: int) -> None:
        """拆掉线路，放口并停掉该人端入口。"""
        if self._human is not None:
            self._human.release(human_entry)
        line = self._lines.pop(human_entry)
        self._serial.release(line.device)
        self._persist()

    def shutdown(self) -> None:
        """放掉所有占口并停听全部人端入口，不拆线路、不改存档。"""
        for line in self._lines.values():
            if self._human is not None:
                self._human.release(line.human_entry)
                line.human_listening = False
            if line.hold == LineHold.HELD:
                self._serial.release(line.device)
            line.hold = LineHold.WAITING
            line.clients.clear()

    def scan(self) -> SerialScan:
        """重新枚举现场设备并更新最近扫描快照。"""
        self._last_scan = self._serial.scan()
        return self._last_scan

    def last_scan(self) -> SerialScan:
        """返回最近一次现场扫描快照，不触发新枚举。"""
        return self._last_scan

    def refresh(self) -> None:
        """对照现场插着的设备，进入等待或再占口。"""
        self._reconcile()

    def retry_line(self, human_entry: int) -> LineStatus:
        """对一条线路再占口、再听人端入口；不补发旧写入，不改编排。"""
        if human_entry not in self._lines:
            raise KeyError(human_entry)
        self._reconcile()
        return self._status(self._lines[human_entry])

    def _has_line(self, human_entry: int) -> bool:
        """判断指定人端入口对应的线路是否仍存在。"""
        return human_entry in self._lines

    def _agent_attached(self, agent: Agent) -> bool:
        """判断指定 Agent 是否仍挂在对应线路上（拆后重建同一入口不算）。"""
        line = self._lines.get(agent.human_entry)
        return line is not None and agent in line.clients

    def _restore(self) -> None:
        """从存档恢复线路并再占口。"""
        for record in self._store.load():
            self._install(record)

    def _install(
        self,
        record: LineArrangement,
        *,
        bind_entry: bool = True,
        human_listening: bool | None = None,
    ) -> None:
        """按编排装上一条线路并向设备占口。"""
        hold = self._serial.occupy(record.device, record.serial_params)
        listening = True
        if human_listening is not None:
            listening = human_listening
        elif bind_entry and self._human is not None:
            listening = self._human.occupy(record.human_entry)
        line = _Line(
            human_entry=record.human_entry,
            device=record.device,
            serial_params=record.serial_params,
            decode=record.decode,
            name=record.name,
            hold=hold,
            human_listening=listening,
        )
        self._lines[record.human_entry] = line
        self._bind_device(line)

    def _bind_device(self, line: _Line) -> None:
        """占口成功后把设备字节接到这条线路的扇出上。"""
        if line.hold != LineHold.HELD:
            return
        entry = line.human_entry
        self._serial.listen(
            line.device,
            lambda data: self._on_device_bytes(entry, data),
        )

    def _reoccupy(
        self,
        line: _Line,
        new_device: SerialIdentity,
        new_params: SerialParams,
        *,
        conflict_message: str,
    ) -> None:
        """放掉旧占口并按新设备/参数占口；冲突时尽量恢复旧占口。"""
        old_device = line.device
        old_params = line.serial_params
        old_hold = line.hold
        if old_hold == LineHold.HELD:
            self._serial.release(old_device)
        hold = self._serial.occupy(new_device, new_params)
        if hold == LineHold.CONFLICT:
            if old_hold == LineHold.HELD:
                line.hold = self._serial.occupy(old_device, old_params)
                self._bind_device(line)
            else:
                line.hold = old_hold
            raise SerialApplyFailed(conflict_message)
        line.device = new_device
        line.serial_params = new_params
        line.hold = hold
        self._bind_device(line)

    def _rekey_entry(self, line: _Line, new_entry: int) -> None:
        """入口迁走后，已挂客户端和扇出都跟到新端口。"""
        old_entry = line.human_entry
        if self._human is not None:
            self._human.release(old_entry)
        self._lines.pop(old_entry)
        line.human_entry = new_entry
        line.human_listening = True
        for client in line.clients:
            client._human_entry = new_entry
        self._lines[new_entry] = line
        self._bind_device(line)

    def _retry_human_entry(self, line: _Line) -> None:
        """入口未听时再绑一次；对方已放口则恢复监听。"""
        if line.human_listening or self._human is None:
            return
        if self._human.occupy(line.human_entry):
            line.human_listening = True

    def _reconcile(self) -> None:
        """对照现场：设备再占口；人端入口未听则再绑。"""
        scan = self._serial.scan()
        self._last_scan = scan
        present = scan.paths
        for line in self._lines.values():
            if line.device not in present:
                if line.hold == LineHold.HELD:
                    self._serial.release(line.device)
                line.hold = LineHold.WAITING
            elif line.hold != LineHold.HELD:
                line.hold = self._serial.occupy(line.device, line.serial_params)
                self._bind_device(line)
            self._retry_human_entry(line)

    def _on_device_bytes(self, human_entry: int, data: bytes) -> None:
        """设备字节以原样送到每个已挂客户端。"""
        line = self._lines.get(human_entry)
        if line is None:
            return
        line.rx_bytes += len(data)
        line.last_rx_at = time.time()
        self._remember(line, data)
        for client in line.clients:
            client._deliver(data)

    def _write_text_from_agent(self, agent: Agent, text: str) -> WriteResult:
        """按线路解码将 Agent 文本写入设备；未占口时明确拒绝且不排队。"""
        line = self._lines.get(agent._human_entry)
        if line is None or agent not in line.clients:
            return WriteResult(ok=False, error="没有这条线路")
        if line.hold == LineHold.WAITING:
            return WriteResult(ok=False, error="等待设备，写入未发送")
        if line.hold == LineHold.CONFLICT:
            return WriteResult(ok=False, error="占用冲突，写入未发送")
        if line.hold != LineHold.HELD:
            return WriteResult(ok=False, error="设备未占口，写入未发送")
        data = text.encode(line.decode, errors="replace")
        if not self._write_from_client(agent, data):
            return WriteResult(ok=False, error="设备未占口，写入未发送")
        return WriteResult(ok=True)

    def _write_from_client(self, client: _Endpoint, data: bytes) -> bool:
        """客户端写入：只有占口时才进设备并扇出；失败不补发。"""
        line = self._lines.get(client._human_entry)
        if line is None or client not in line.clients:
            return False
        if line.hold != LineHold.HELD:
            return False
        self._serial.write(line.device, data)
        line.tx_bytes += len(data)
        self._remember(line, data)
        for other in line.clients:
            if other is not client:
                other._deliver(data)
        return True

    def _detach_client(self, client: _Endpoint) -> None:
        """客户端离开后不再扇出给它；线路仍占口。"""
        line = self._lines.get(client._human_entry)
        if line is None:
            return
        if client in line.clients:
            line.clients.remove(client)

    def _remember(self, line: _Line, data: bytes) -> None:
        """记下一段最近原字节，超出上限丢掉更早的。"""
        line.recent.extend(data)
        extra = len(line.recent) - _RECENT_LIMIT
        if extra > 0:
            del line.recent[:extra]

    def _persist(self) -> None:
        """把当前编排写入存档。"""
        self._store.save(
            tuple(
                LineArrangement(
                    human_entry=line.human_entry,
                    device=line.device,
                    serial_params=line.serial_params,
                    decode=line.decode,
                    name=line.name,
                )
                for line in self._lines.values()
            )
        )

    def _status(self, line: _Line) -> LineStatus:
        """把内部记录变成对外可见的线路状态。"""
        return LineStatus(
            human_entry=line.human_entry,
            device=line.device,
            serial_params=line.serial_params,
            decode=line.decode,
            hold=line.hold,
            human_clients=sum(1 for item in line.clients if isinstance(item, Client)),
            agent_connected=any(isinstance(item, Agent) for item in line.clients),
            name=line.name,
            human_listening=line.human_listening,
            rx_bytes=line.rx_bytes,
            tx_bytes=line.tx_bytes,
            last_rx_at=line.last_rx_at,
        )

    def _decode_of(self, human_entry: int) -> str:
        """该线路当前的解码；线路没了则回落到默认 GBK。"""
        line = self._lines.get(human_entry)
        if line is None:
            return "gbk"
        return line.decode


def _clean_name(name: str) -> str:
    """线路名称给自己看，最多 32 个字。"""
    return name.strip()[:32]
