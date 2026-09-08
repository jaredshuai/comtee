"""串口适配器缝：按 USB 身份认设备，丢掉蓝牙虚拟口。"""

from comtee import Comtee, LineArrangement, LineHold, SerialParams, UsbIdentity
from comtee.usb_serial import PortBusy, PortSnapshot, UsbSerial, usb_identity_paths


def test_蓝牙虚拟口不出现在设备列表() -> None:
    """枚举只留下带 VID:PID 与序列号的 USB 串口。"""
    ftdi = PortSnapshot(
        path="COM6",
        vid=0x0403,
        pid=0x6001,
        serial="FT123",
        hwid="USB VID:PID=0403:6001 SER=FT123",
        description="USB Serial Port",
    )
    bluetooth = PortSnapshot(
        path="COM3",
        vid=None,
        pid=None,
        serial=None,
        hwid="BTHENUM\\{00001101-0000-1000-8000-00805F9B34FB}",
        description="Standard Serial over Bluetooth link",
    )

    found = usb_identity_paths((ftdi, bluetooth))

    assert found == {UsbIdentity(vid=0x0403, pid=0x6001, serial="FT123"): "COM6"}


def test_带VID的蓝牙虚拟口也丢掉() -> None:
    """跳过蓝牙不靠「没有 VID」，BTHENUM 本身就要丢。"""
    bluetooth = PortSnapshot(
        path="COM4",
        vid=0x0A12,
        pid=0x0001,
        serial="BTH001",
        hwid="BTHENUM\\{00001101-0000-1000-8000-00805F9B34FB}",
        description="Standard Serial over Bluetooth link",
    )
    assert usb_identity_paths((bluetooth,)) == {}


def test_同一USB身份COM号变了仍认成同一台设备() -> None:
    """路径只是此刻打开它的路，身份不变。"""
    device = UsbIdentity(vid=0x0403, pid=0x6001, serial="FT123")
    first = PortSnapshot(
        path="COM6",
        vid=0x0403,
        pid=0x6001,
        serial="FT123",
        hwid="USB VID:PID=0403:6001 SER=FT123",
        description="USB Serial Port",
    )
    moved = PortSnapshot(
        path="COM9",
        vid=0x0403,
        pid=0x6001,
        serial="FT123",
        hwid="USB VID:PID=0403:6001 SER=FT123",
        description="USB Serial Port",
    )

    assert usb_identity_paths((first,))[device] == "COM6"
    assert usb_identity_paths((moved,))[device] == "COM9"


class _Handle:
    """记下打开路径与写入。"""

    def __init__(self, path: str) -> None:
        self.path = path
        self.written = bytearray()

    def write(self, data: bytes) -> None:
        """收下打进口的字节。"""
        self.written.extend(data)

    def close(self) -> None:
        """放口。"""


class _MemoryStore:
    """本文件用的进程内编排存档。"""

    def __init__(self) -> None:
        self._lines: tuple[LineArrangement, ...] = ()

    def load(self) -> tuple[LineArrangement, ...]:
        """读出上一份编排。"""
        return self._lines

    def save(self, lines: tuple[LineArrangement, ...]) -> None:
        """写入当前编排。"""
        self._lines = lines


def test_按USB身份打开且COM变了仍打开新路径() -> None:
    """占口按身份找此刻路径，不钉死 COM 号。"""
    device = UsbIdentity(vid=0x0403, pid=0x6001, serial="FT123")
    ports = [
        PortSnapshot(
            path="COM6",
            vid=0x0403,
            pid=0x6001,
            serial="FT123",
            hwid="USB VID:PID=0403:6001 SER=FT123",
            description="USB Serial Port",
        )
    ]
    opened: list[str] = []

    def list_ports() -> list[PortSnapshot]:
        return list(ports)

    def open_port(path: str, _params: SerialParams) -> _Handle:
        opened.append(path)
        return _Handle(path)

    adapter = UsbSerial(list_ports, open_port)
    assert adapter.occupy(device, SerialParams()) == LineHold.HELD
    ports[0] = PortSnapshot(
        path="COM9",
        vid=0x0403,
        pid=0x6001,
        serial="FT123",
        hwid="USB VID:PID=0403:6001 SER=FT123",
        description="USB Serial Port",
    )
    adapter.release(device)
    assert adapter.occupy(device, SerialParams()) == LineHold.HELD
    assert opened == ["COM6", "COM9"]


def test_真设备被占用时线路是占用冲突() -> None:
    """打开失败映射为占用冲突，不是等待设备。"""
    device = UsbIdentity(vid=0x0403, pid=0x6001, serial="FT123")
    snapshot = PortSnapshot(
        path="COM6",
        vid=0x0403,
        pid=0x6001,
        serial="FT123",
        hwid="USB VID:PID=0403:6001 SER=FT123",
        description="USB Serial Port",
    )

    def list_ports() -> list[PortSnapshot]:
        return [snapshot]

    def open_port(path: str, _params: SerialParams) -> _Handle:
        raise PortBusy(path)

    hub = Comtee(UsbSerial(list_ports, open_port), _MemoryStore())
    hub.create_line(2222, device)
    [line] = hub.list_lines()
    assert line.hold == LineHold.CONFLICT
    assert line.hold != LineHold.WAITING


def test_身份不在现场时占口是等待设备() -> None:
    """枚举不到该 USB 身份则等待，不是占用冲突。"""

    def list_ports() -> list[PortSnapshot]:
        return []

    def open_port(path: str, _params: SerialParams) -> _Handle:
        raise AssertionError(f"不该打开 {path}")

    adapter = UsbSerial(list_ports, open_port)
    missing = UsbIdentity(vid=0x0403, pid=0x6001, serial="FT123")
    assert adapter.occupy(missing, SerialParams()) == LineHold.WAITING
    assert adapter.occupy(missing, SerialParams()) != LineHold.CONFLICT
