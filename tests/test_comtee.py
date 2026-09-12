"""串通模块缝：假设备上编排线路并占口。"""

from collections.abc import Callable

import pytest

from comtee import (
    AgentForbidden,
    ArrangementRejected,
    Comtee,
    HumanEntryOccupied,
    LineArrangement,
    LineHold,
    SerialApplyFailed,
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
        self._written: dict[UsbIdentity, bytearray] = {}
        self._ingress: dict[UsbIdentity, bytearray] = {}
        self._listeners: dict[UsbIdentity, Callable[[bytes], None]] = {}
        self._paths: dict[UsbIdentity, str] = {}
        self._occupied_path: dict[UsbIdentity, str] = {}
        self._on_change: Callable[[], None] | None = None
        self.occupy_calls = 0

    def plug(self, device: UsbIdentity, path: str = "COM6") -> None:
        """让该 USB 身份出现在现场；路径可变。"""
        self._present.add(device)
        self._paths[device] = path
        self._notify()

    def unplug(self, device: UsbIdentity) -> None:
        """拔掉该 USB 身份。"""
        self._present.discard(device)
        self._paths.pop(device, None)
        self._notify()

    def present(self) -> frozenset[UsbIdentity]:
        """此刻现场插着的 USB 身份。"""
        return frozenset(self._present)

    def watch(self, on_change: Callable[[], None]) -> None:
        """登记插拔通知。"""
        self._on_change = on_change

    def path_of(self, device: UsbIdentity) -> str:
        """此刻枚举到的路径。"""
        return self._paths[device]

    def occupied_path(self, device: UsbIdentity) -> str:
        """最近一次占口时用的路径。"""
        return self._occupied_path[device]

    def _notify(self) -> None:
        """有人在听时上报插拔。"""
        if self._on_change is not None:
            self._on_change()

    def mark_busy(self, device: UsbIdentity) -> None:
        """模拟设备已被别人占用、打不开。"""
        self._busy.add(device)

    def clear_busy(self, device: UsbIdentity) -> None:
        """模拟别人放口；设备仍在场。"""
        self._busy.discard(device)

    def occupy(self, device: UsbIdentity, params: SerialParams) -> LineHold:
        """按身份占口；不在则等待，被占则冲突。"""
        self.occupy_calls += 1
        if device not in self._present:
            return LineHold.WAITING
        if device in self._busy:
            return LineHold.CONFLICT
        self._held[device] = params
        self._written[device] = bytearray()
        self._occupied_path[device] = self._paths[device]
        return LineHold.HELD

    def release(self, device: UsbIdentity) -> None:
        """放掉该设备。"""
        self._held.pop(device, None)
        self._written.pop(device, None)
        self._listeners.pop(device, None)
        self._occupied_path.pop(device, None)

    def listen(self, device: UsbIdentity, on_bytes: Callable[[bytes], None]) -> None:
        """登记设备字节回调。"""
        self._listeners[device] = on_bytes

    def write(self, device: UsbIdentity, data: bytes) -> None:
        """记下打进设备的原字节。"""
        self._ingress.setdefault(device, bytearray()).extend(data)
        held = self._written.get(device)
        if held is not None:
            held.extend(data)

    def emit(self, device: UsbIdentity, data: bytes) -> None:
        """模拟设备打出原字节。"""
        listener = self._listeners.get(device)
        if listener is not None:
            listener(data)

    def written(self, device: UsbIdentity) -> bytes:
        """取出已打进设备的原字节。"""
        return bytes(self._written.get(device, b""))

    def ingress(self, device: UsbIdentity) -> bytes:
        """串通过适配器写下的全部字节，放口后仍保留。"""
        return bytes(self._ingress.get(device, b""))

    def is_held(self, device: UsbIdentity) -> bool:
        """该设备此刻是否被串通占着。"""
        return device in self._held

    def held_params(self, device: UsbIdentity) -> SerialParams:
        """当前占口使用的串口参数。"""
        return self._held[device]


class FakeHuman:
    """假人端入口：可模拟绑定成功或本机端口被占。"""

    def __init__(self) -> None:
        """新建一份空的入口表。"""
        self.listening: set[int] = set()
        self.blocked: set[int] = set()
        self.occupy_calls: list[int] = []
        self.release_calls: list[int] = []

    def attach(self, hub: Comtee) -> None:
        """接到串通；本假入口不需要保留 hub。"""
        del hub

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


def test_占用冲突在对方放口后对照现场再占口() -> None:
    """占用冲突不是终态：别人放口后刷新应占口。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    serial.mark_busy(device)
    hub = Comtee(serial, MemoryStore())
    hub.create_line(2222, device)
    assert hub.list_lines()[0].hold == LineHold.CONFLICT

    serial.clear_busy(device)
    hub.refresh()

    [line] = hub.list_lines()
    assert line.hold == LineHold.HELD
    assert serial.is_held(device)


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


def test_设备字节以原样到达每个已挂客户端() -> None:
    """同一线路上多个人端都能收到设备上来的原字节。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, MemoryStore())
    hub.create_line(2222, device)
    first = hub.attach_client(2222)
    second = hub.attach_client(2222)

    payload = b"\x00\xff\x1b[32mOK\r\n"
    serial.emit(device, payload)

    assert first.received() == payload
    assert second.received() == payload


def test_客户端写入以原样到达设备和其他客户端() -> None:
    """任一客户端写下的原字节进设备，并出现在其他客户端。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, MemoryStore())
    hub.create_line(2222, device)
    first = hub.attach_client(2222)
    second = hub.attach_client(2222)

    first.write(b"ls\r")

    assert serial.written(device) == b"ls\r"
    assert second.received() == b"ls\r"
    assert first.received() == b""


def test_同时写不拒绝也不设写锁() -> None:
    """两个客户端都能写下，串通不排队、不拒绝。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, MemoryStore())
    hub.create_line(2222, device)
    first = hub.attach_client(2222)
    second = hub.attach_client(2222)

    first.write(b"A")
    second.write(b"B")

    assert serial.written(device) == b"AB"
    assert first.received() == b"B"
    assert second.received() == b"A"


def test_客户端离开后不再收到后续字节且线路仍占口() -> None:
    """离开的客户端停收；留下的继续共驾，占口不放。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, MemoryStore())
    hub.create_line(2222, device)
    first = hub.attach_client(2222)
    second = hub.attach_client(2222)

    second.leave()
    serial.emit(device, b"still-here")
    first.write(b"x")

    assert first.received() == b"still-here"
    assert second.received() == b""
    assert serial.written(device) == b"x"
    assert serial.is_held(device)


def test_离开的客户端再写不会进设备() -> None:
    """离开等于不再参与三通，写下的也不进设备、不到其他客户端。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, MemoryStore())
    hub.create_line(2222, device)
    first = hub.attach_client(2222)
    second = hub.attach_client(2222)

    second.leave()
    second.write(b"ghost")

    assert serial.written(device) == b""
    assert first.received() == b""


def test_拔掉USB后线路还在客户端不断开且为等待设备() -> None:
    """USB 消失不拆线路、不踢客户端，状态是等待设备而不是占用冲突。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, MemoryStore())
    hub.create_line(2222, device)
    client = hub.attach_client(2222)

    serial.unplug(device)

    [line] = hub.list_lines()
    assert line.human_entry == 2222
    assert line.device == device
    assert line.hold == LineHold.WAITING
    assert line.hold != LineHold.CONFLICT
    assert not serial.is_held(device)
    assert client.write(b"still-attached") is False
    peer = hub.attach_client(2222)
    assert client.write(b"ping") is False
    assert peer.received() == b""
    assert hub.list_lines()[0].human_clients == 2


def test_等待设备期间写入不进设备且不踢客户端() -> None:
    """等待时写下的忽略进设备，线路与客户端都还在。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, MemoryStore())
    hub.create_line(2222, device)
    client = hub.attach_client(2222)
    peer = hub.attach_client(2222)
    serial.unplug(device)

    assert client.write(b"ignored") is False

    [line] = hub.list_lines()
    assert line.hold == LineHold.WAITING
    assert not serial.is_held(device)
    assert serial.ingress(device) == b""
    assert peer.received() == b""
    late = hub.attach_agent(2222)
    assert late.received() == ""


def test_未占口写入失败恢复后不补发() -> None:
    """等待期间的写入必须失败；插回后不得偷偷补发旧命令。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, MemoryStore())
    hub.create_line(2222, device)
    client = hub.attach_client(2222)
    serial.unplug(device)

    assert client.write(b"stale") is False
    serial.plug(device, path="COM11")
    hub.retry_line(2222)

    [line] = hub.list_lines()
    assert line.hold == LineHold.HELD
    assert serial.written(device) == b""
    assert serial.ingress(device) == b""
    assert client.write(b"fresh") is True
    assert serial.written(device) == b"fresh"


def test_占用冲突时写入失败对方放口后不补发() -> None:
    """占用冲突时写入失败；对方放口后重试占口，旧写入仍不补发。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    serial.mark_busy(device)
    hub = Comtee(serial, MemoryStore())
    hub.create_line(2222, device)
    client = hub.attach_client(2222)

    assert hub.list_lines()[0].hold == LineHold.CONFLICT
    assert client.write(b"blocked") is False
    serial.clear_busy(device)
    after = hub.retry_line(2222)

    assert after.hold == LineHold.HELD
    assert serial.is_held(device)
    assert serial.written(device) == b""
    assert serial.ingress(device) == b""


def test_同一USB身份插回后即使路径变了也再占口() -> None:
    """插回同一身份则再占口，设备字节重新流动。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, MemoryStore())
    hub.create_line(2222, device)
    client = hub.attach_client(2222)
    serial.unplug(device)

    serial.plug(device, path="COM9")
    serial.emit(device, b"back")
    client.write(b"up")

    [line] = hub.list_lines()
    assert line.hold == LineHold.HELD
    assert serial.is_held(device)
    assert serial.occupied_path(device) == "COM9"
    assert client.received() == b"back"
    assert serial.written(device) == b"up"


def test_另一台设备再现不会误接到这条线路() -> None:
    """等待中的线路只认自己的 USB 身份。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, MemoryStore())
    hub.create_line(2222, device)
    client = hub.attach_client(2222)
    serial.unplug(device)
    stranger = UsbIdentity(vid=0x0403, pid=0x6001, serial="OTHER")
    serial.plug(stranger, path="COM7")
    serial.emit(stranger, b"nope")

    [line] = hub.list_lines()
    assert line.device == device
    assert line.hold == LineHold.WAITING
    assert not serial.is_held(device)
    assert not serial.is_held(stranger)
    assert client.received() == b""


def test_Agent按线路解码看见字而管子仍是原字节() -> None:
    """Agent 读到 GBK 解码后的字；人端仍拿到原字节。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, MemoryStore())
    hub.create_line(2222, device)
    human = hub.attach_client(2222)
    agent = hub.attach_agent(2222)

    payload = "你好".encode("gbk")
    serial.emit(device, payload)

    assert human.received() == payload
    assert agent.received() == "你好"


def test_人改解码后Agent按新规则看见字() -> None:
    """解码只是 Agent 视图；人改完之后新字节按新规则读。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, MemoryStore())
    hub.create_line(2222, device)
    agent = hub.attach_agent(2222)
    hub.change_line(2222, decode="utf-8")

    serial.emit(device, "你好".encode())

    assert agent.received() == "你好"


def test_Agent写入以原字节进设备() -> None:
    """Agent 写下的不经过解码改写，原样进设备并出现在人端。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, MemoryStore())
    hub.create_line(2222, device)
    human = hub.attach_client(2222)
    agent = hub.attach_agent(2222)

    raw = "显示".encode("gbk")
    agent.write(raw)

    assert serial.written(device) == raw
    assert human.received() == raw


def test_Agent进场带最近缓冲且不进线路状态() -> None:
    """进场可读视图带最近内容；缓冲不是线路状态上的字段。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, MemoryStore())
    hub.create_line(2222, device)
    serial.emit(device, "prompt> ".encode("gbk"))

    agent = hub.attach_agent(2222)

    assert agent.received() == "prompt> "
    [line] = hub.list_lines()
    assert not hasattr(line, "recent")
    assert not hasattr(line, "buffer")


def test_最近缓冲有上限且重启后不恢复() -> None:
    """缓冲不是永久历史：只留一段尾巴，存档恢复后是空的。"""
    store = MemoryStore()
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, store)
    hub.create_line(2222, device)
    serial.emit(device, (b"x" * 20000) + b"END")

    text = hub.attach_agent(2222).received()
    assert text.endswith("END")
    assert len(text) < 20003

    restarted = FakeSerial()
    restarted.plug(device)
    restored = Comtee(restarted, store)
    assert restored.attach_agent(2222).received() == ""


def test_Agent调用编排或改串口参数和解码被拒绝() -> None:
    """编排权留在人手里。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, MemoryStore())
    hub.create_line(2222, device)
    agent = hub.attach_agent(2222)
    other = UsbIdentity(vid=0x0403, pid=0x6001, serial="FT999")
    serial.plug(other)

    with pytest.raises(AgentForbidden):
        agent.create_line(3333, other)
    with pytest.raises(AgentForbidden):
        agent.change_line(decode="utf-8")
    with pytest.raises(AgentForbidden):
        agent.remove_line(2222)

    [line] = hub.list_lines()
    assert line.decode == "gbk"
    assert line.human_entry == 2222


def test_Agent必须指名线路串通不猜设备() -> None:
    """两条线路时，Agent 只能看到它指名的那一条。"""
    serial = FakeSerial()
    first = _plugged(serial, "FT123")
    second = _plugged(serial, "FT456")
    hub = Comtee(serial, MemoryStore())
    hub.create_line(2222, first)
    hub.create_line(3333, second)
    serial.emit(first, b"AAA")
    serial.emit(second, b"BBB")

    agent = hub.attach_agent(2222)
    assert agent.received() == "AAA"
    with pytest.raises(KeyError):
        hub.attach_agent(9999)


def test_列出线路能看见谁连着() -> None:
    """面板要看人端数量和有没有 Agent，不看字节流。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, MemoryStore())
    hub.create_line(2222, device)

    [empty] = hub.list_lines()
    assert empty.human_clients == 0
    assert empty.agent_connected is False

    first = hub.attach_client(2222)
    hub.attach_client(2222)
    hub.attach_agent(2222)
    [busy] = hub.list_lines()
    assert busy.human_clients == 2
    assert busy.agent_connected is True

    first.leave()
    [after] = hub.list_lines()
    assert after.human_clients == 1
    assert after.agent_connected is True


def test_退出放口但不拆编排() -> None:
    """托盘退出才放口；存档里的线路还在，再打开会再占。"""
    store = MemoryStore()
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, store)
    hub.create_line(2222, device)
    hub.shutdown()

    assert hub.list_lines()[0].human_entry == 2222
    assert not serial.is_held(device)

    revived = FakeSerial()
    revived.plug(device)
    restored = Comtee(revived, store)
    assert restored.list_lines()[0].hold == LineHold.HELD
    assert revived.is_held(device)


def test_创建线路时入口被占则不留下半条线路() -> None:
    """交互创建失败不得占设备、不得写入编排。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    human = FakeHuman()
    human.blocked.add(2222)
    hub = Comtee(serial, MemoryStore(), human=human)

    with pytest.raises(HumanEntryOccupied):
        hub.create_line(2222, device)

    assert hub.list_lines() == ()
    assert not serial.is_held(device)
    assert human.listening == set()


def test_恢复编排时入口被占线路仍在且标为未监听() -> None:
    """启动恢复不能因为入口冲突把人的线路丢掉。"""
    store = MemoryStore()
    device = UsbIdentity(vid=0x0403, pid=0x6001, serial="FT123")
    store.save(
        (
            LineArrangement(
                human_entry=2222,
                device=device,
                serial_params=SerialParams(),
                decode="gbk",
                name="AC 控制台",
            ),
        )
    )
    serial = FakeSerial()
    serial.plug(device)
    human = FakeHuman()
    human.blocked.add(2222)
    hub = Comtee(serial, store, human=human)

    [line] = hub.list_lines()
    assert line.human_entry == 2222
    assert line.name == "AC 控制台"
    assert line.hold == LineHold.HELD
    assert line.human_listening is False
    assert serial.is_held(device)
    assert human.listening == set()


def test_端口冲突可重试监听且不改编排() -> None:
    """端口冲突必须有显式重试；对方未放口时仍失败，放口后恢复监听。"""
    store = MemoryStore()
    device = UsbIdentity(vid=0x0403, pid=0x6001, serial="FT123")
    store.save(
        (
            LineArrangement(
                human_entry=2222,
                device=device,
                serial_params=SerialParams(),
                decode="gbk",
                name="AC 控制台",
            ),
        )
    )
    serial = FakeSerial()
    serial.plug(device)
    human = FakeHuman()
    human.blocked.add(2222)
    hub = Comtee(serial, store, human=human)
    client = hub.attach_client(2222)
    assert client.write(b"keep") is True
    assert hub.retry_line(2222).human_listening is False
    assert hub.list_lines()[0].human_entry == 2222
    assert hub.list_lines()[0].name == "AC 控制台"
    assert store.load()[0].human_entry == 2222

    human.blocked.discard(2222)
    recovered = hub.retry_line(2222)

    assert recovered.human_listening is True
    assert recovered.hold == LineHold.HELD
    assert 2222 in human.listening
    assert store.load()[0].human_entry == 2222
    assert serial.written(device) == b"keep"


def test_恢复时入口被占对方放口后对照现场再听() -> None:
    """人端入口占用也不是终态：别人放口后刷新应再听。"""
    store = MemoryStore()
    device = UsbIdentity(vid=0x0403, pid=0x6001, serial="FT123")
    store.save(
        (
            LineArrangement(
                human_entry=2222,
                device=device,
                serial_params=SerialParams(),
                decode="gbk",
            ),
        )
    )
    serial = FakeSerial()
    serial.plug(device)
    human = FakeHuman()
    human.blocked.add(2222)
    hub = Comtee(serial, store, human=human)
    assert hub.list_lines()[0].human_listening is False

    human.blocked.discard(2222)
    hub.refresh()

    [line] = hub.list_lines()
    assert line.human_listening is True
    assert 2222 in human.listening


def test_改入口失败时原线路配置和连接都保留() -> None:
    """新入口绑不上时，不得先拆旧入口再失败。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    human = FakeHuman()
    hub = Comtee(serial, MemoryStore(), human=human)
    hub.create_line(2222, device, name="实验台")
    client = hub.attach_client(2222)
    human.blocked.add(3333)

    with pytest.raises(HumanEntryOccupied):
        hub.change_line(2222, new_entry=3333)

    [line] = hub.list_lines()
    assert line.human_entry == 2222
    assert line.name == "实验台"
    assert line.human_listening is True
    assert 2222 in human.listening
    assert 3333 not in human.listening
    assert client.write(b"stay") is True
    assert serial.written(device) == b"stay"


def test_改入口成功后旧入口释放且客户端跟到新入口() -> None:
    """迁移成功后，旧端口不再听，指名新端口才能继续写。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    human = FakeHuman()
    hub = Comtee(serial, MemoryStore(), human=human)
    hub.create_line(2222, device)
    client = hub.attach_client(2222)

    hub.change_line(2222, new_entry=3333)

    [line] = hub.list_lines()
    assert line.human_entry == 3333
    assert line.human_listening is True
    assert 2222 not in human.listening
    assert 3333 in human.listening
    assert client.write(b"after") is True
    assert serial.written(device) == b"after"
    with pytest.raises(KeyError):
        hub.attach_agent(2222)
    moved = hub.attach_agent(3333)
    assert moved.write(b"!") is True
    assert serial.written(device) == b"after!"


def test_只改解码或名称不重新占口() -> None:
    """字符集和名称不是串口参数，已有占口应保持。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, MemoryStore())
    hub.create_line(2222, device)
    calls = serial.occupy_calls

    hub.change_line(2222, decode="utf-8", name="备用")

    [line] = hub.list_lines()
    assert line.decode == "utf-8"
    assert line.name == "备用"
    assert serial.occupy_calls == calls
    assert serial.is_held(device)


def test_改串口参数时保留未改字段() -> None:
    """完整设置必须带着原校验、停止位和流控，不能用默认 8N1 盖掉。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, MemoryStore())
    original = SerialParams(
        baudrate=9600,
        data_bits=7,
        parity="E",
        stop_bits=2,
        flow_control="rtscts",
    )
    hub.create_line(2222, device, serial_params=original)

    hub.change_line(
        2222,
        serial_params=SerialParams(
            baudrate=115200,
            data_bits=7,
            parity="E",
            stop_bits=2,
            flow_control="rtscts",
        ),
    )

    [line] = hub.list_lines()
    assert line.serial_params == SerialParams(
        baudrate=115200,
        data_bits=7,
        parity="E",
        stop_bits=2,
        flow_control="rtscts",
    )
    assert serial.held_params(device) == line.serial_params


def test_等待设备时改参数先保存待接入后再占口() -> None:
    """设备不在时保存成功，插回按新参数占口，不补发旧写入。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, MemoryStore())
    hub.create_line(2222, device)
    client = hub.attach_client(2222)
    serial.unplug(device)
    assert client.write(b"old") is False

    hub.change_line(2222, serial_params=SerialParams(baudrate=115200))

    [waiting] = hub.list_lines()
    assert waiting.serial_params.baudrate == 115200
    assert waiting.hold == LineHold.WAITING
    serial.plug(device, path="COM9")
    [held] = hub.list_lines()
    assert held.hold == LineHold.HELD
    assert serial.held_params(device) == SerialParams(baudrate=115200)
    assert serial.written(device) == b""


def test_参数应用失败则保留原串口配置() -> None:
    """重新占口失败不得把用户原来的参数写进存档。"""
    store = MemoryStore()
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, store)
    hub.create_line(
        2222,
        device,
        serial_params=SerialParams(baudrate=19200, flow_control="xonxoff"),
    )
    serial.mark_busy(device)

    with pytest.raises(SerialApplyFailed):
        hub.change_line(2222, serial_params=SerialParams(baudrate=115200))

    [line] = hub.list_lines()
    assert line.serial_params == SerialParams(baudrate=19200, flow_control="xonxoff")
    assert store.load()[0].serial_params == line.serial_params


def test_收发计数只统计实际进出设备的字节() -> None:
    """未发送的写入不能当成设备流量，也不能冒充最近收到。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, MemoryStore())
    hub.create_line(2222, device)
    client = hub.attach_client(2222)
    serial.emit(device, b"abc")
    assert client.write(b"xy") is True
    [held] = hub.list_lines()
    assert held.rx_bytes == 3
    assert held.tx_bytes == 2
    assert held.last_rx_at is not None
    serial.unplug(device)
    assert client.write(b"nope") is False
    [waiting] = hub.list_lines()
    assert waiting.rx_bytes == 3
    assert waiting.tx_bytes == 2


def test_线路名称会写进存档() -> None:
    """名称是人填的用途，重启后还在。"""
    store = MemoryStore()
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, store)
    hub.create_line(2222, device, name="AC 控制台")

    restarted = FakeSerial()
    restarted.plug(device)
    restored = Comtee(restarted, store)
    assert restored.list_lines()[0].name == "AC 控制台"
