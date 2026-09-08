"""串通：人端入口与设备一对一编排，线路在则占口。"""

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
        self._lines[record.human_entry] = _Line(
            human_entry=record.human_entry,
            device=record.device,
            serial_params=record.serial_params,
            decode=record.decode,
            hold=hold,
        )

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
