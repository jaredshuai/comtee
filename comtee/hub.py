"""串通：人端入口与设备一对一编排，线路在则占口。"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class ArrangementRejected(Exception):
    """两条线路不得共享同一人端入口或同一台设备。"""


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
    clients: list[Client] = field(default_factory=list)


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


class Comtee:
    """串通模块：编排线路、列出状态；占口与恢复藏在实现里。"""

    def __init__(self, serial: SerialPort, store: ArrangementStore) -> None:
        """注入串口与编排存档适配器，并恢复上一份编排。"""
        self._serial = serial
        self._store = store
        self._lines: dict[int, _Line] = {}
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

    def _on_device_bytes(self, human_entry: int, data: bytes) -> None:
        """设备字节以原样送到每个已挂客户端。"""
        line = self._lines.get(human_entry)
        if line is None:
            return
        for client in line.clients:
            client._deliver(data)

    def _write_from_client(self, client: Client, data: bytes) -> None:
        """客户端写入：进设备，并出现在其他客户端。"""
        line = self._lines.get(client._human_entry)
        if line is None or client not in line.clients:
            return
        if line.hold == LineHold.HELD:
            self._serial.write(line.device, data)
        for other in line.clients:
            if other is not client:
                other._deliver(data)

    def _detach_client(self, client: Client) -> None:
        """客户端离开后不再扇出给它；线路仍占口。"""
        line = self._lines.get(client._human_entry)
        if line is None:
            return
        if client in line.clients:
            line.clients.remove(client)

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
        )
