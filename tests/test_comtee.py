"""串通模块缝：假设备上编排线路并占口。"""

import pytest

from comtee import (
    AgentForbidden,
    AgentSession,
    ArrangementRejected,
    BluetoothIdentity,
    Comtee,
    HumanEntryOccupied,
    LineArrangement,
    LineHold,
    SerialApplyFailed,
    SerialParams,
    UsbIdentity,
    identity_from_dict,
    parse_identity_key,
)
from tests.fakes import FakeHuman, FakeSerial, MemoryStore
from tests.fakes import plugged as _plugged


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


def test_参数应用失败时旧监听和客户端关系保持() -> None:
    """新参数打不开时，旧占口、旧监听和已挂客户端都必须留下。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    human = FakeHuman()
    hub = Comtee(serial, MemoryStore(), human=human)
    hub.create_line(2222, device, serial_params=SerialParams(baudrate=19200))
    client = hub.attach_client(2222)
    serial.fail_next_occupy()

    with pytest.raises(SerialApplyFailed):
        hub.change_line(2222, serial_params=SerialParams(baudrate=115200))

    [line] = hub.list_lines()
    assert line.serial_params == SerialParams(baudrate=19200)
    assert line.hold == LineHold.HELD
    assert line.human_listening is True
    assert 2222 in human.listening
    assert client.write(b"keep") is True
    assert serial.written(device) == b"keep"
    assert serial.held_params(device) == SerialParams(baudrate=19200)
    serial.emit(device, b"from-dev")
    assert client.received() == b"from-dev"


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


def test_设置里改绑新蓝牙设备时放开旧口并占住新口且写盘() -> None:
    """蓝牙重配对生成新身份后，线路可通过 change_line 切换设备并拒绝撞线。"""
    store = MemoryStore()
    serial = FakeSerial()
    old_bt = BluetoothIdentity(hwid="BTHENUM\\OLD_0001")
    new_bt = BluetoothIdentity(hwid="BTHENUM\\NEW_0002")
    other = _plugged(serial, "FT999")
    serial.plug(old_bt, path="COM4")
    serial.plug(new_bt, path="COM5")
    hub = Comtee(serial, store)
    hub.create_line(2222, old_bt, name="蓝牙开关")
    hub.create_line(3333, other)

    with pytest.raises(ArrangementRejected):
        hub.change_line(2222, device=other)

    hub.change_line(2222, device=new_bt)

    assert not serial.is_held(old_bt)
    assert serial.is_held(new_bt)
    [line_2222, _] = hub.list_lines()
    assert line_2222.device == new_bt
    assert line_2222.hold == LineHold.HELD
    assert store.load()[0].device == new_bt


def test_刷新和扫描通过同一串口缝更新最近扫描快照() -> None:
    """Comtee 通过 SerialPort.scan 缓存现场扫描结果，不靠外层旁路重扫。"""
    serial = FakeSerial()
    usb = UsbIdentity(vid=0x0403, pid=0x6001, serial="FT123")
    serial.plug(usb, path="COM6")
    serial.set_unidentified(2)
    hub = Comtee(serial, MemoryStore())
    assert hub.last_scan().paths == {usb: "COM6"}
    assert hub.last_scan().usb == 1
    assert hub.last_scan().unidentified == 2

    bt = BluetoothIdentity(hwid="BTHENUM\\NEW_0002")
    serial.plug(bt, path="COM5")
    assert hub.last_scan().paths == {usb: "COM6", bt: "COM5"}
    assert hub.last_scan().bluetooth == 1

    calls_before = serial.scan_calls
    hub.refresh()
    assert serial.scan_calls == calls_before + 1
    assert hub.last_scan().paths == {usb: "COM6", bt: "COM5"}
    assert hub.last_scan().bluetooth == 1

    serial.set_unidentified(0)
    direct = hub.scan()
    assert serial.scan_calls == calls_before + 2
    assert direct.unidentified == 0
    assert hub.last_scan() == direct


def test_设备身份自带键编解码标签和字典序列化() -> None:
    """USB 与蓝牙身份自行负责键、标签与字典读写，不泄漏给调用方做分支。"""
    usb = UsbIdentity(vid=0x0403, pid=0x6001, serial="FT123")
    assert usb.key() == "0403:6001|FT123"
    assert parse_identity_key(usb.key()) == usb
    assert usb.label() == "USB 0403:6001 · 序列号 FT123"
    assert identity_from_dict(usb.to_dict()) == usb

    bt = BluetoothIdentity(
        hwid=r"bthenum\{00001101-0000-1000-8000-00805f9b34fb}_localmfg&0046\8&2eccb597&0&04220520037b_c00000000"
    )
    assert bt.key().startswith("BT|BTHENUM\\")
    assert parse_identity_key(bt.key()) == bt
    assert bt.label() == "蓝牙 地址 04:22:05:20:03:7B · 实例 C00000000"
    assert identity_from_dict(bt.to_dict()) == bt

    raw_bt = BluetoothIdentity(hwid=r"BTHENUM\CUSTOM_DEV")
    assert raw_bt.label() == "蓝牙 硬件标识 CUSTOM_DEV"

    with pytest.raises(ValueError, match="不支持的设备类型"):
        identity_from_dict({"device_type": "tcp"})
    with pytest.raises(ValueError, match="无效的蓝牙身份键"):
        parse_identity_key("BT|   ")
    with pytest.raises(ValueError, match="无效的设备身份键"):
        parse_identity_key("malformed")


def test_AgentSession直接完成双向解码与端口迁移跟随() -> None:
    """AgentSession 统一负责按线路解码读写、冲突拒绝与端口迁移跟随。"""
    serial = FakeSerial()
    human = FakeHuman()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, MemoryStore(), human=human)
    hub.create_line(2222, device, decode="gbk")
    session = AgentSession(hub)

    serial.emit(device, "你好".encode("gbk"))
    read_ok = session.read(2222)
    assert read_ok.ok is True and read_ok.text == "你好"

    write_ok = session.write(2222, "中文")
    assert write_ok.ok is True
    assert serial.written(device) == "中文".encode("gbk")

    hub.change_line(2222, new_entry=3333)
    assert session.write(2222, "old").error == "没有这条线路"
    assert session.write(3333, "new").ok is True
    assert serial.written(device).endswith(b"new")

    hub.remove_line(3333)
    assert session.write(3333, "gone").error == "没有这条线路"
    hub.create_line(3333, device, decode="utf-8")
    assert session.write(3333, "reborn").ok is True
    assert serial.written(device).endswith(b"reborn")
    serial.emit(device, "重连".encode())
    assert session.read(3333).text == "重连"

    serial.unplug(device)
    assert session.write(3333, "x").error == "等待设备，写入未发送"

    session.close()
    assert hub.list_lines()[0].agent_connected is False


def test_串通关闭时一并释放串口占口与人端监听() -> None:
    """shutdown 一次释放全部占口和人端监听，并允许清理后由新实例重绑。"""
    serial = FakeSerial()
    human = FakeHuman()
    device = _plugged(serial, "FT123")
    hub = Comtee(serial, MemoryStore(), human=human)
    hub.create_line(2222, device)
    assert 2222 in human.listening

    hub.shutdown()

    assert not serial.is_held(device)
    assert 2222 not in human.listening
    assert hub.list_lines()[0].human_listening is False
