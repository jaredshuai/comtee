"""串通模块缝：假设备上编排线路并占口。"""

import pytest

from comtee import (
    ArrangementRejected,
    Comtee,
    LineArrangement,
    LineHold,
    SerialParams,
    UsbIdentity,
)


class MemoryStore:
    """进程内编排存档，同一实例可模拟重启后仍在的那一份。"""

    def __init__(self) -> None:
        self._lines: tuple[LineArrangement, ...] = ()

    def load(self) -> tuple[LineArrangement, ...]:
        """读出上一份线路编排。"""
        return self._lines

    def save(self, lines: tuple[LineArrangement, ...]) -> None:
        """写入当前线路编排。"""
        self._lines = lines


class FakeSerial:
    """假串口：按 USB 身份插拔、占口与放口。"""

    def __init__(self) -> None:
        self._present: set[UsbIdentity] = set()
        self._busy: set[UsbIdentity] = set()
        self._held: dict[UsbIdentity, SerialParams] = {}

    def plug(self, device: UsbIdentity) -> None:
        """让该 USB 身份出现在现场。"""
        self._present.add(device)

    def mark_busy(self, device: UsbIdentity) -> None:
        """模拟设备已被别人占用、打不开。"""
        self._busy.add(device)

    def occupy(self, device: UsbIdentity, params: SerialParams) -> LineHold:
        """按身份占口；不在则等待，被占则冲突。"""
        if device not in self._present:
            return LineHold.WAITING
        if device in self._busy:
            return LineHold.CONFLICT
        self._held[device] = params
        return LineHold.HELD

    def release(self, device: UsbIdentity) -> None:
        """放掉该设备。"""
        self._held.pop(device, None)

    def is_held(self, device: UsbIdentity) -> bool:
        """该设备此刻是否被串通占着。"""
        return device in self._held

    def held_params(self, device: UsbIdentity) -> SerialParams:
        """当前占口使用的串口参数。"""
        return self._held[device]


def test_创建线路后即使没有客户端也占口() -> None:
    """线路存在则占口，默认 9600 8N1 无流控、解码 GBK。"""
    serial = FakeSerial()
    device = UsbIdentity(vid=0x0403, pid=0x6001, serial="FT123")
    serial.plug(device)
    hub = Comtee(serial, MemoryStore())

    hub.create_line(2222, device)

    lines = hub.list_lines()
    assert len(lines) == 1
    assert lines[0].human_entry == 2222
    assert lines[0].device == device
    assert lines[0].hold == LineHold.HELD
    assert lines[0].serial_params == SerialParams()
    assert lines[0].decode == "gbk"
    assert serial.is_held(device)


def _plugged(serial: FakeSerial, serial_number: str) -> UsbIdentity:
    """插入一台假设备并返回其 USB 身份。"""
    device = UsbIdentity(vid=0x0403, pid=0x6001, serial=serial_number)
    serial.plug(device)
    return device


def test_两台设备不能钉同一人端入口() -> None:
    """已有入口被占用时，再创建必须拒绝。"""
    serial = FakeSerial()
    first = _plugged(serial, "FT123")
    second = _plugged(serial, "FT456")
    hub = Comtee(serial, MemoryStore())
    hub.create_line(2222, first)

    with pytest.raises(ArrangementRejected):
        hub.create_line(2222, second)

    lines = hub.list_lines()
    assert len(lines) == 1
    assert lines[0].device == first
    assert serial.is_held(first)
    assert not serial.is_held(second)


def test_两条线路不能钉同一台设备() -> None:
    """已占口的设备不能再被另一条线路钉上。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    other = _plugged(serial, "FT456")
    hub = Comtee(serial, MemoryStore())
    hub.create_line(2222, device)

    with pytest.raises(ArrangementRejected):
        hub.create_line(3333, device)

    lines = hub.list_lines()
    assert len(lines) == 1
    assert lines[0].human_entry == 2222
    hub.create_line(3333, other)
    assert {line.human_entry for line in hub.list_lines()} == {2222, 3333}


def test_设备打不开时是占用冲突不是等待设备() -> None:
    """设备在场但打不开时线路仍在，状态为占用冲突。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    serial.mark_busy(device)
    hub = Comtee(serial, MemoryStore())

    hub.create_line(2222, device)

    [line] = hub.list_lines()
    assert line.hold == LineHold.CONFLICT
    assert line.hold != LineHold.WAITING
    assert not serial.is_held(device)


def test_能改一条线路的串口参数和解码() -> None:
    """改参数后状态可见，占口使用新串口参数。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, MemoryStore())
    hub.create_line(2222, device)

    hub.change_line(
        2222,
        serial_params=SerialParams(baudrate=115200, flow_control="rtscts"),
        decode="utf-8",
    )

    [line] = hub.list_lines()
    assert line.serial_params == SerialParams(baudrate=115200, flow_control="rtscts")
    assert line.decode == "utf-8"
    assert line.hold == LineHold.HELD
    assert serial.held_params(device) == SerialParams(
        baudrate=115200, flow_control="rtscts"
    )


def test_拆线路后放口且人端入口可再钉() -> None:
    """拆掉线路则放掉设备，该入口可钉给另一台设备。"""
    serial = FakeSerial()
    first = _plugged(serial, "FT123")
    second = _plugged(serial, "FT456")
    hub = Comtee(serial, MemoryStore())
    hub.create_line(2222, first)

    hub.remove_line(2222)

    assert hub.list_lines() == ()
    assert not serial.is_held(first)
    hub.create_line(2222, second)
    [line] = hub.list_lines()
    assert line.device == second
    assert serial.is_held(second)
    assert not serial.is_held(first)


def test_进程退出再打开后上一份编排还在() -> None:
    """新进程读同一份存档后恢复线路并再占口。"""
    store = MemoryStore()
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, store)
    hub.create_line(2222, device)
    hub.change_line(
        2222,
        serial_params=SerialParams(baudrate=115200),
        decode="utf-8",
    )

    restarted = FakeSerial()
    restarted.plug(device)
    restored = Comtee(restarted, store)

    [line] = restored.list_lines()
    assert line.human_entry == 2222
    assert line.device == device
    assert line.serial_params == SerialParams(baudrate=115200)
    assert line.decode == "utf-8"
    assert line.hold == LineHold.HELD
    assert restarted.is_held(device)
    assert restarted.held_params(device) == SerialParams(baudrate=115200)


def test_拆掉的线路重启后不再恢复() -> None:
    """拆线路写入存档后，新进程不应再占该口、再听该入口。"""
    store = MemoryStore()
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, store)
    hub.create_line(2222, device)
    hub.remove_line(2222)

    restarted = FakeSerial()
    restarted.plug(device)
    restored = Comtee(restarted, store)

    assert restored.list_lines() == ()
    assert not restarted.is_held(device)
