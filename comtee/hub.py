"""串通：人端入口与设备一对一编排，线路在则占口。"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

_RECENT_LIMIT = 4096


class ArrangementRejected(Exception):
    """两条线路不得共享同一人端入口或同一台设备。"""


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


@dataclass(frozen=True)
class LineArrangement:
    """需要写盘并在启动时恢复的线路编排，不含占口结果。"""

    human_entry: int
    device: UsbIdentity
    serial_params: SerialParams
    decode: str


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


@dataclass
class _Line:
    """一条线路的内部记录。"""

    human_entry: int
    device: UsbIdentity
    serial_params: SerialParams = field(default_factory=SerialParams)
    decode: str = "gbk"
    hold: LineHold = LineHold.WAITING
    clients: list[Client | Agent] = field(default_factory=list)
    recent: bytearray = field(default_factory=bytearray)


class Client:
    """挂在某条线路上的一个客户端，收发明文原字节。"""

    def __init__(self, hub: Comtee, human_entry: int) -> None:
        """绑定到串通上的一条线路。"""
        self._hub = hub
        self._human_entry = human_entry
        self._inbox = bytearray()

    def received(self) -> bytes:
        """取出尚未取走的、扇出到本客户端的原字节。"""
        data = bytes(self._inbox)
        self._inbox.clear()
        return data

    def write(self, data: bytes) -> None:
        """写下原字节：进设备，并出现在其他客户端。"""
        self._hub._write_from_client(self, data)

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

    def received(self) -> str:
        """取出尚未取走的可读字，按该线路解码。"""
        raw = bytes(self._inbox)
        self._inbox.clear()
        return raw.decode(self._hub._decode_of(self._human_entry), errors="replace")

    def write(self, data: bytes) -> None:
        """写下仍是原字节，进设备并出现在其他客户端。"""
        self._hub._write_from_client(self, data)

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

    def __init__(self, serial: SerialPort, store: ArrangementStore) -> None:
        """注入串口与编排存档适配器，并恢复上一份编排。"""
        self._serial = serial
        self._store = store
        self._lines: dict[int, _Line] = {}
        self._serial.watch(self._reconcile)
        self._restore()

    def create_line(self, human_entry: int, device: UsbIdentity) -> None:
        """创建一对一线路并占口，与有没有客户端无关。"""
        if human_entry in self._lines:
            raise ArrangementRejected("人端入口已被另一条线路占用")
        if any(line.device == device for line in self._lines.values()):
            raise ArrangementRejected("设备已被另一条线路占用")
        params = SerialParams()
        self._install(
            LineArrangement(
                human_entry=human_entry,
                device=device,
                serial_params=params,
                decode="gbk",
            )
        )
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
        serial_params: SerialParams | None = None,
        decode: str | None = None,
    ) -> None:
        """改一条线路的串口参数和/或解码，并按新参数重新占口。"""
        line = self._lines[human_entry]
        if serial_params is not None:
            self._serial.release(line.device)
            line.serial_params = serial_params
            line.hold = self._serial.occupy(line.device, serial_params)
            self._bind_device(line)
        if decode is not None:
            line.decode = decode
        self._persist()

    def remove_line(self, human_entry: int) -> None:
        """拆掉线路，放口并停掉该人端入口。"""
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

    def _install(self, record: LineArrangement) -> None:
        """按编排装上一条线路并向设备占口。"""
        hold = self._serial.occupy(record.device, record.serial_params)
        line = _Line(
            human_entry=record.human_entry,
            device=record.device,
            serial_params=record.serial_params,
            decode=record.decode,
            hold=hold,
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

    def _reconcile(self) -> None:
        """对照现场插着的设备：消失则等待，同一身份再现则再占口。"""
        present = self._serial.present()
        for line in self._lines.values():
            if line.device not in present:
                if line.hold == LineHold.HELD:
                    self._serial.release(line.device)
                line.hold = LineHold.WAITING
                continue
            if line.hold == LineHold.HELD:
                continue
            if line.hold != LineHold.WAITING:
                continue
            line.hold = self._serial.occupy(line.device, line.serial_params)
            self._bind_device(line)

    def _on_device_bytes(self, human_entry: int, data: bytes) -> None:
        """设备字节以原样送到每个已挂客户端。"""
        line = self._lines.get(human_entry)
        if line is None:
            return
        self._remember(line, data)
        for client in line.clients:
            client._deliver(data)

    def _write_from_client(self, client: Client | Agent, data: bytes) -> None:
        """客户端写入：进设备，并出现在其他客户端。"""
        line = self._lines.get(client._human_entry)
        if line is None or client not in line.clients:
            return
        if line.hold == LineHold.HELD:
            self._serial.write(line.device, data)
        self._remember(line, data)
        for other in line.clients:
            if other is not client:
                other._deliver(data)

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
        )

    def _decode_of(self, human_entry: int) -> str:
        """该线路当前的解码；线路没了则回落到默认 GBK。"""
        line = self._lines.get(human_entry)
        if line is None:
            return "gbk"
        return line.decode
