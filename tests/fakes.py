"""共享测试替身：假串口、假人端入口、内存存档与等待辅助。"""

from __future__ import annotations

import time
from collections.abc import Callable

from comtee import (
    BluetoothIdentity,
    Client,
    LineArrangement,
    LineHold,
    SerialIdentity,
    SerialParams,
    SerialScan,
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
    """假串口：按 USB 或蓝牙身份插拔、占口、扫描与放口。"""

    def __init__(self) -> None:
        self._present: set[SerialIdentity] = set()
        self._busy: set[SerialIdentity] = set()
        self._held: dict[SerialIdentity, SerialParams] = {}
        self._written: dict[SerialIdentity, bytearray] = {}
        self._ingress: dict[SerialIdentity, bytearray] = {}
        self._listeners: dict[SerialIdentity, Callable[[bytes], None]] = {}
        self._paths: dict[SerialIdentity, str] = {}
        self._occupied_path: dict[SerialIdentity, str] = {}
        self._on_change: Callable[[], None] | None = None
        self._fail_occupy = 0
        self._unidentified = 0
        self.occupy_calls = 0
        self.scan_calls = 0

    def plug(self, device: SerialIdentity, path: str = "COM6") -> None:
        """让该稳定设备身份出现在现场；路径可变。"""
        self._present.add(device)
        self._paths[device] = path
        self._notify()

    def unplug(self, device: SerialIdentity) -> None:
        """拔掉该设备身份。"""
        self._present.discard(device)
        self._paths.pop(device, None)
        self._notify()

    def set_unidentified(self, count: int) -> None:
        """设置模拟枚举里被忽略的无身份串口数量。"""
        self._unidentified = count

    def scan(self) -> SerialScan:
        """枚举此刻现场插着的可支持串口与诊断计数。"""
        self.scan_calls += 1
        usb = sum(1 for item in self._present if isinstance(item, UsbIdentity))
        bluetooth = sum(
            1 for item in self._present if isinstance(item, BluetoothIdentity)
        )
        return SerialScan(
            paths={item: self._paths[item] for item in self._present},
            usb=usb,
            bluetooth=bluetooth,
            unidentified=self._unidentified,
        )

    def watch(self, on_change: Callable[[], None]) -> None:
        """登记插拔通知。"""
        self._on_change = on_change

    def path_of(self, device: SerialIdentity) -> str:
        """此刻枚举到的路径。"""
        return self._paths[device]

    def occupied_path(self, device: SerialIdentity) -> str:
        """最近一次占口时用的路径。"""
        return self._occupied_path[device]

    def _notify(self) -> None:
        """有人在听时上报插拔。"""
        if self._on_change is not None:
            self._on_change()

    def mark_busy(self, device: SerialIdentity) -> None:
        """模拟设备已被别人占用、打不开。"""
        self._busy.add(device)

    def fail_next_occupy(self, times: int = 1) -> None:
        """让接下来若干次占口失败，用于测参数或换设备回滚。"""
        self._fail_occupy = times

    def clear_busy(self, device: SerialIdentity) -> None:
        """模拟别人放口；设备仍在场。"""
        self._busy.discard(device)

    def occupy(self, device: SerialIdentity, params: SerialParams) -> LineHold:
        """按身份占口；不在则等待，被占则冲突。"""
        self.occupy_calls += 1
        if self._fail_occupy > 0:
            self._fail_occupy -= 1
            if device not in self._present:
                return LineHold.WAITING
            return LineHold.CONFLICT
        if device not in self._present:
            return LineHold.WAITING
        if device in self._busy:
            return LineHold.CONFLICT
        self._held[device] = params
        self._written[device] = bytearray()
        self._occupied_path[device] = self._paths[device]
        return LineHold.HELD

    def release(self, device: SerialIdentity) -> None:
        """放掉该设备。"""
        self._held.pop(device, None)
        self._written.pop(device, None)
        self._listeners.pop(device, None)
        self._occupied_path.pop(device, None)

    def listen(self, device: SerialIdentity, on_bytes: Callable[[bytes], None]) -> None:
        """登记设备字节回调。"""
        self._listeners[device] = on_bytes

    def write(self, device: SerialIdentity, data: bytes) -> None:
        """记下打进设备的原字节。"""
        self._ingress.setdefault(device, bytearray()).extend(data)
        held = self._written.get(device)
        if held is not None:
            held.extend(data)

    def emit(self, device: SerialIdentity, data: bytes) -> None:
        """模拟设备打出原字节。"""
        listener = self._listeners.get(device)
        if listener is not None:
            listener(data)

    def written(self, device: SerialIdentity) -> bytes:
        """取出已打进设备的原字节。"""
        return bytes(self._written.get(device, b""))

    def ingress(self, device: SerialIdentity) -> bytes:
        """串通通过适配器写下的全部字节，放口后仍保留。"""
        return bytes(self._ingress.get(device, b""))

    def is_held(self, device: SerialIdentity) -> bool:
        """该设备此刻是否被串通占着。"""
        return device in self._held

    def held_params(self, device: SerialIdentity) -> SerialParams:
        """当前占口使用的串口参数。"""
        return self._held[device]


class FakeHuman:
    """假人端入口：可模拟绑定成功或本机端口被占。"""

    def __init__(self) -> None:
        """新建一份空的入口表。"""
        self._attach: Callable[[int], Client] | None = None
        self.listening: set[int] = set()
        self.blocked: set[int] = set()
        self.occupy_calls: list[int] = []
        self.release_calls: list[int] = []

    def attach(self, on_connect: Callable[[int], Client]) -> None:
        """接收串通客户端挂接回调。"""
        self._attach = on_connect

    def occupy(self, human_entry: int) -> bool:
        """开始听该人端入口；被挡住则失败。"""
        self.occupy_calls.append(human_entry)
        if human_entry in self.blocked:
            return False
        self.listening.add(human_entry)
        return True

    def release(self, human_entry: int) -> None:
        """停掉该人端入口。"""
        self.release_calls.append(human_entry)
        self.listening.discard(human_entry)


def plugged(serial: FakeSerial, name: str, path: str = "COM6") -> UsbIdentity:
    """插上一根带稳定序列号的假 USB 串口并返回其身份。"""
    device = UsbIdentity(vid=0x0403, pid=0x6001, serial=name)
    serial.plug(device, path=path)
    return device


def wait_until(ok: Callable[[], bool], timeout: float = 1.5) -> None:
    """轮询等待异步条件成立。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ok():
            return
        time.sleep(0.02)
    raise AssertionError("条件一直不成立")
