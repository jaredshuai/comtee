"""按 USB 身份枚举并打开串口；COM 路径只是此刻打开它的路。

本机核对（不进门禁）：插已知 FTDI，usb_identity_paths 应出现其 VID:PID 与序列号；
用其他程序占住该 COM 后再 occupy，应为占用冲突；蓝牙虚拟口不得出现在列表里。
"""

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

from comtee.hub import LineHold, SerialParams, UsbIdentity


@dataclass(frozen=True)
class PortSnapshot:
    """一次枚举看到的串口：身份字段加上此刻路径。"""

    path: str
    vid: int | None
    pid: int | None
    serial: str | None
    hwid: str
    description: str


def usb_identity_paths(ports: Iterable[PortSnapshot]) -> dict[UsbIdentity, str]:
    """列出 USB 串口身份到此刻 COM 路径；丢掉蓝牙和非 USB。"""
    found: dict[UsbIdentity, str] = {}
    for port in ports:
        identity = _usb_identity(port)
        if identity is None:
            continue
        found[identity] = port.path
    return found


def _usb_identity(port: PortSnapshot) -> UsbIdentity | None:
    """能钉死的 USB 身份；蓝牙虚拟口和缺身份的口都丢掉。"""
    if _is_bluetooth(port):
        return None
    if port.vid is None or port.pid is None:
        return None
    if not port.serial:
        return None
    return UsbIdentity(vid=port.vid, pid=port.pid, serial=port.serial)


def _is_bluetooth(port: PortSnapshot) -> bool:
    """Windows 蓝牙虚拟口：BTHENUM 或描述里带 Bluetooth。"""
    if "BTHENUM" in port.hwid.upper():
        return True
    return "bluetooth" in port.description.lower()


class PortBusy(Exception):
    """此刻打不开：设备已被别人占用。"""


class OpenedPort(Protocol):
    """一次占口拿到的可读、可写、可关的串口。"""

    def read(self, size: int = 4096) -> bytes:
        """取出设备打出的原字节；没有则空。"""
        ...

    def write(self, data: bytes) -> None:
        """把原字节打进设备。"""
        ...

    def close(self) -> None:
        """放口。"""
        ...


class UsbSerial:
    """串口适配器：按 USB 身份占口，COM 号只当路径。"""

    def __init__(
        self,
        list_ports: Callable[[], Iterable[PortSnapshot]],
        open_port: Callable[[str, SerialParams], OpenedPort],
    ) -> None:
        """注入枚举与打开，便于测试不碰真 COM。"""
        self._list_ports = list_ports
        self._open_port = open_port
        self._held: dict[UsbIdentity, OpenedPort] = {}
        self._listeners: dict[UsbIdentity, Callable[[bytes], None]] = {}
        self._readers: dict[UsbIdentity, threading.Thread] = {}
        self._stops: dict[UsbIdentity, threading.Event] = {}
        self._on_change: Callable[[], None] | None = None

    def occupy(self, device: UsbIdentity, params: SerialParams) -> LineHold:
        """按身份打开此刻路径；不在则等待，打不开则占用冲突。"""
        path = usb_identity_paths(self._list_ports()).get(device)
        if path is None:
            return LineHold.WAITING
        try:
            handle = self._open_port(path, params)
        except PortBusy:
            return LineHold.CONFLICT
        self._held[device] = handle
        self._ensure_reader(device)
        return LineHold.HELD

    def release(self, device: UsbIdentity) -> None:
        """放掉该设备并停掉读线程。"""
        stop = self._stops.pop(device, None)
        if stop is not None:
            stop.set()
        thread = self._readers.pop(device, None)
        handle = self._held.pop(device, None)
        self._listeners.pop(device, None)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        if handle is not None:
            handle.close()

    def listen(self, device: UsbIdentity, on_bytes: Callable[[bytes], None]) -> None:
        """登记设备字节回调，并在已占口时开始泵字节。"""
        self._listeners[device] = on_bytes
        self._ensure_reader(device)

    def _ensure_reader(self, device: UsbIdentity) -> None:
        """占口且有回调时启动读线程；线程已死则再拉起来。"""
        if device not in self._held or device not in self._listeners:
            return
        existing = self._readers.get(device)
        if existing is not None and existing.is_alive():
            return
        stop = threading.Event()
        self._stops[device] = stop
        thread = threading.Thread(
            target=self._read_loop,
            args=(device, stop),
            daemon=True,
        )
        self._readers[device] = thread
        thread.start()

    def _read_loop(self, device: UsbIdentity, stop: threading.Event) -> None:
        """循环读取真串口，把设备字节送到登记的回调。"""
        while not stop.is_set():
            handle = self._held.get(device)
            listener = self._listeners.get(device)
            if handle is None or listener is None:
                return
            try:
                data = handle.read(4096)
            except OSError:
                on_change = self._on_change
                if on_change is not None:
                    on_change()
                return
            if data:
                listener(data)
            elif stop.wait(0.05):
                return

    def write(self, device: UsbIdentity, data: bytes) -> None:
        """把客户端写下的原字节打进已占的口。"""
        self._held[device].write(data)

    def present(self) -> frozenset[UsbIdentity]:
        """此刻现场插着的 USB 身份。"""
        return frozenset(self.paths())

    def paths(self) -> dict[UsbIdentity, str]:
        """USB 身份到此刻 COM 路径。"""
        return usb_identity_paths(self._list_ports())

    def watch(self, on_change: Callable[[], None]) -> None:
        """插拔变化时由调用方触发对照。"""
        self._on_change = on_change


def list_pyserial_ports() -> list[PortSnapshot]:
    """用 pyserial 枚举本机串口。"""
    from serial.tools import list_ports

    return [
        PortSnapshot(
            path=info.device,
            vid=info.vid,
            pid=info.pid,
            serial=info.serial_number,
            hwid=info.hwid or "",
            description=info.description or "",
        )
        for info in list_ports.comports()
    ]


def open_pyserial(path: str, params: SerialParams) -> OpenedPort:
    """打开此刻 COM 路径；被占则 PortBusy。"""
    import serial

    parity = {
        "N": serial.PARITY_NONE,
        "E": serial.PARITY_EVEN,
        "O": serial.PARITY_ODD,
    }.get(params.parity, serial.PARITY_NONE)
    stopbits = {
        1: serial.STOPBITS_ONE,
        2: serial.STOPBITS_TWO,
    }.get(int(params.stop_bits), serial.STOPBITS_ONE)
    try:
        return serial.Serial(
            port=path,
            baudrate=params.baudrate,
            bytesize=params.data_bits,
            parity=parity,
            stopbits=stopbits,
            xonxoff=params.flow_control == "xonxoff",
            rtscts=params.flow_control == "rtscts",
            dsrdtr=params.flow_control == "dsrdtr",
            timeout=0.2,
        )
    except serial.SerialException as exc:
        raise PortBusy(path) from exc


def windows_usb_serial() -> UsbSerial:
    """Win11 上按 USB 身份占口的适配器。"""
    return UsbSerial(list_pyserial_ports, open_pyserial)
