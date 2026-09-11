"""串通：人端入口与设备一对一编排，线路在则占口。"""

from __future__ import annotations

import time
from collections.abc import Callable
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
    """用 VID:PID 与序列号辨认的一台设备。"""

    vid: int
    pid: int
    serial: str


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
    device: UsbIdentity
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
    device: UsbIdentity
    serial_params: SerialParams
    decode: str
    name: str = ""


class SerialPort(Protocol):
    """按 USB 身份占口、放口的串口适配器。"""

    def occupy(self, device: UsbIdentity, params: SerialParams) -> LineHold:
        """打开并独占该设备；打不开则占用冲突，不在则等待设备。"""
        ...

    def release(self, device: UsbIdentity) -> None:
        """放掉该设备。"""
        ...

    def listen(self, device: UsbIdentity, on_bytes: Callable[[bytes], None]) -> None:
        """设备上来的原字节回调给串通。"""
        ...

    def write(self, device: UsbIdentity, data: bytes) -> None:
        """把客户端写下的原字节打进设备。"""
        ...

    def present(self) -> frozenset[UsbIdentity]:
        """此刻现场插着的 USB 身份。"""
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

    def attach(self, hub: Comtee) -> None:
        """接到串通，连上后挂客户端。"""
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
    device: UsbIdentity
    serial_params: SerialParams = field(default_factory=SerialParams)
    decode: str = "gbk"
    name: str = ""
    hold: LineHold = LineHold.WAITING
    human_listening: bool = True
    clients: list[Client | Agent] = field(default_factory=list)
    recent: bytearray = field(default_factory=bytearray)
    rx_bytes: int = 0
    tx_bytes: int = 0
    last_rx_at: float | None = None


class Client:
    """挂在某条线路上的一个客户端，收发明文原字节。"""

    def __init__(self, hub: Comtee, human_entry: int) -> None:
        """绑定到串通上的一条线路。"""
        self._hub = hub
        self._human_entry = human_entry
        self._inbox = bytearray()

    @property
    def human_entry(self) -> int:
        """此刻这条客户端挂着的人端入口。"""
        return self._human_entry

    def received(self) -> bytes:
        """取出尚未取走的、扇出到本客户端的原字节。"""
        data = bytes(self._inbox)
        self._inbox.clear()
        return data

    def write(self, data: bytes) -> bool:
        """写下原字节：进设备才算成功，并出现在其他客户端。"""
        return self._hub._write_from_client(self, data)

    def leave(self) -> None:
        """离开线路，不再收到后续字节。"""
        self._hub._detach_client(self)

    def _deliver(self, data: bytes) -> None:
        """收下扇出到本客户端的原字节。"""
        self._inbox.extend(data)


class Agent:
    """挂在已有线路上的 Agent 端：读解码后的字，写原字节。"""

    def __init__(self, hub: Comtee, human_entry: int) -> None:
        """绑定到指名的那条线路，串通不猜设备。"""
        self._hub = hub
        self._human_entry = human_entry
        self._inbox = bytearray()

    @property
    def human_entry(self) -> int:
        """此刻这条 Agent 挂着的人端入口。"""
        return self._human_entry

    def received(self) -> str:
        """取出尚未取走的可读字，按该线路解码。"""
        raw = bytes(self._inbox)
        self._inbox.clear()
        return raw.decode(self._hub._decode_of(self._human_entry), errors="replace")

    def write(self, data: bytes) -> bool:
        """写下仍是原字节；只有进设备才算成功。"""
        return self._hub._write_from_client(self, data)

    def leave(self) -> None:
        """离开线路，不再收到后续字节。"""
        self._hub._detach_client(self)

    def _deliver(self, data: bytes) -> None:
        """收下扇出到本 Agent 的原字节，读时再解码。"""
        self._inbox.extend(data)

    def create_line(self, human_entry: int, device: UsbIdentity) -> None:
        """拒绝：Agent 不能创建线路。"""
        raise AgentForbidden("Agent 不能编排线路")

    def change_line(self, **_kwargs: object) -> None:
        """拒绝：Agent 不能改串口参数或解码。"""
        raise AgentForbidden("Agent 不能改串口参数和解码")

    def remove_line(self, human_entry: int) -> None:
        """拒绝：Agent 不能拆线路。"""
        raise AgentForbidden("Agent 不能编排线路")


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
            human.attach(self)
        self._serial.watch(self._reconcile)
        self._restore()

    def create_line(
        self,
        human_entry: int,
        device: UsbIdentity,
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
        name: str | None = None,
        serial_params: SerialParams | None = None,
        decode: str | None = None,
    ) -> None:
        """改一条线路的入口、名称、串口参数和/或解码。"""
        line = self._lines[human_entry]
        pending_entry: int | None = None
        if new_entry is not None and new_entry != human_entry:
            if new_entry in self._lines:
                raise ArrangementRejected("人端入口已被另一条线路占用")
            if self._human is not None and not self._human.occupy(new_entry):
                raise HumanEntryOccupied(new_entry)
            pending_entry = new_entry
        try:
            if serial_params is not None and serial_params != line.serial_params:
                self._apply_serial_params(line, serial_params)
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
        """放掉所有占口，不拆线路、不改存档。"""
        for line in self._lines.values():
            if line.hold == LineHold.HELD:
                self._serial.release(line.device)
            line.hold = LineHold.WAITING
            line.clients.clear()

    def refresh(self) -> None:
        """对照现场插着的设备，进入等待或再占口。"""
        self._reconcile()

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

    def _apply_serial_params(self, line: _Line, params: SerialParams) -> None:
        """按新参数占口；失败则回到原参数，不把失败配置写盘。"""
        old = line.serial_params
        if line.hold == LineHold.HELD:
            self._serial.release(line.device)
        hold = self._serial.occupy(line.device, params)
        if hold == LineHold.CONFLICT:
            restored = self._serial.occupy(line.device, old)
            line.hold = restored
            self._bind_device(line)
            raise SerialApplyFailed()
        line.serial_params = params
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

    def _reconcile(self) -> None:
        """对照现场：不在则等待；在场且未占口（等待或占用冲突）则再占口。"""
        present = self._serial.present()
        for line in self._lines.values():
            if line.device not in present:
                if line.hold == LineHold.HELD:
                    self._serial.release(line.device)
                line.hold = LineHold.WAITING
                continue
            if line.hold == LineHold.HELD:
                self._bind_device(line)
                continue
            line.hold = self._serial.occupy(line.device, line.serial_params)
            self._bind_device(line)

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

    def _write_from_client(self, client: Client | Agent, data: bytes) -> bool:
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

    def _detach_client(self, client: Client | Agent) -> None:
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
