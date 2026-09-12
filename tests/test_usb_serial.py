"""串口适配器缝：按 USB 身份认设备，丢掉蓝牙虚拟口。"""

import queue
import threading
import time
from collections.abc import Callable

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
    """记下打开路径与写入；无设备输出。"""

    def __init__(self, path: str) -> None:
        self.path = path
        self.written = bytearray()
        self.closed = False

    def read(self, size: int = 4096) -> bytes:
        """没有设备输出时返回空。"""
        return b""

    def write(self, data: bytes) -> None:
        """收下打进口的字节。"""
        self.written.extend(data)

    def close(self) -> None:
        """放口。"""
        self.closed = True


class _FeedHandle:
    """测试里可投喂设备输出的假串口。"""

    def __init__(self, path: str) -> None:
        """记下打开路径，并用队列模拟设备打出的字节。"""
        self.path = path
        self.written = bytearray()
        self.closed = False
        self._chunks: queue.Queue[bytes | None] = queue.Queue()

    def feed(self, data: bytes) -> None:
        """模拟设备打出一段字节。"""
        self._chunks.put(data)

    def read(self, size: int = 4096) -> bytes:
        """取出待读字节；关闭或超时则空。"""
        try:
            chunk = self._chunks.get(timeout=0.05)
        except queue.Empty:
            return b""
        if chunk is None:
            return b""
        return chunk[:size]

    def write(self, data: bytes) -> None:
        """收下打进口的字节。"""
        self.written.extend(data)

    def close(self) -> None:
        """放口并唤醒可能堵在 read 上的线程。"""
        self.closed = True
        self._chunks.put(None)


class _DyingHandle:
    """第一次读取就失败，用来观察断开后会不会通知对照现场。"""

    def __init__(self, path: str) -> None:
        """记下打开路径。"""
        self.path = path
        self.closed = False

    def read(self, size: int = 4096) -> bytes:
        """模拟设备突然消失。"""
        raise OSError("device gone")

    def write(self, data: bytes) -> None:
        """写入在本测试里用不到。"""

    def close(self) -> None:
        """放口。"""
        self.closed = True


class _FailOnceThenFeedHandle(_FeedHandle):
    """第一次读取失败，之后仍可投喂设备输出。"""

    def __init__(self, path: str) -> None:
        """先记下打开路径，并记住还没失败过。"""
        super().__init__(path)
        self._failed = False

    def read(self, size: int = 4096) -> bytes:
        """第一次抛错，随后按队列取出设备字节。"""
        if not self._failed:
            self._failed = True
            raise OSError("device hiccup")
        return super().read(size)


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


def _ftdi_snapshot(path: str = "COM6") -> PortSnapshot:
    """一块带序列号的 FTDI，给读路径测试用。"""
    return PortSnapshot(
        path=path,
        vid=0x0403,
        pid=0x6001,
        serial="FT123",
        hwid="USB VID:PID=0403:6001 SER=FT123",
        description="USB Serial Port",
    )


def _wait_until(ok: Callable[[], bool], timeout: float = 1.5) -> None:
    """等到条件成立。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ok():
            return
        time.sleep(0.02)
    raise AssertionError("条件一直不成立")


def test_占口后设备输出送到listen回调() -> None:
    """listen 不只是登记：真适配器要把设备打出的字节送到回调。"""
    device = UsbIdentity(vid=0x0403, pid=0x6001, serial="FT123")
    handle = _FeedHandle("COM6")
    got: list[bytes] = []

    def list_ports() -> list[PortSnapshot]:
        return [_ftdi_snapshot()]

    def open_port(path: str, _params: SerialParams) -> _FeedHandle:
        assert path == "COM6"
        return handle

    adapter = UsbSerial(list_ports, open_port)
    adapter.listen(device, got.append)
    assert adapter.occupy(device, SerialParams()) == LineHold.HELD
    handle.feed(b"\x00hello")
    _wait_until(lambda: got == [b"\x00hello"])
    adapter.release(device)
    assert handle.closed is True


def test_先占口再listen也能收到设备输出() -> None:
    """Hub 的顺序是 occupy 然后 listen，两条登记顺序都要能泵字节。"""
    device = UsbIdentity(vid=0x0403, pid=0x6001, serial="FT123")
    handle = _FeedHandle("COM6")
    got: list[bytes] = []

    adapter = UsbSerial(lambda: [_ftdi_snapshot()], lambda path, _p: handle)
    assert adapter.occupy(device, SerialParams()) == LineHold.HELD
    adapter.listen(device, got.append)
    handle.feed(b"late-bind")
    _wait_until(lambda: got == [b"late-bind"])
    adapter.release(device)


def test_放口后不再投递设备字节() -> None:
    """release 必须停掉读线程，避免关口后仍回调。"""
    device = UsbIdentity(vid=0x0403, pid=0x6001, serial="FT123")
    handle = _FeedHandle("COM6")
    got: list[bytes] = []
    adapter = UsbSerial(lambda: [_ftdi_snapshot()], lambda path, _p: handle)
    adapter.listen(device, got.append)
    adapter.occupy(device, SerialParams())
    handle.feed(b"one")
    _wait_until(lambda: got == [b"one"])
    adapter.release(device)
    handle.feed(b"two")
    time.sleep(0.2)
    assert got == [b"one"]


def test_读取失败会通知对照现场() -> None:
    """设备突然消失时，适配器要触发 watch，而不是把异常吞进后台线程。"""
    device = UsbIdentity(vid=0x0403, pid=0x6001, serial="FT123")
    handle = _DyingHandle("COM6")
    notified = threading.Event()
    adapter = UsbSerial(lambda: [_ftdi_snapshot()], lambda path, _p: handle)
    adapter.watch(notified.set)
    adapter.listen(device, lambda _data: None)
    adapter.occupy(device, SerialParams())
    assert notified.wait(1.5)
    adapter.release(device)


def test_读取失败后对照现场能再收到设备输出() -> None:
    """读线程通知对照现场时自己还活着，不得挡住下一根读线程。"""
    device = UsbIdentity(vid=0x0403, pid=0x6001, serial="FT123")
    handle = _FailOnceThenFeedHandle("COM6")
    got: list[bytes] = []
    adapter = UsbSerial(lambda: [_ftdi_snapshot()], lambda path, _p: handle)

    def on_change() -> None:
        """对照现场时重新登记回调，模拟 Hub 在 HELD 上再 bind。"""
        adapter.listen(device, got.append)

    adapter.watch(on_change)
    adapter.listen(device, got.append)
    adapter.occupy(device, SerialParams())
    handle.feed(b"after-hiccup")
    _wait_until(lambda: got == [b"after-hiccup"])
    adapter.release(device)
