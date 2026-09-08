"""Agent 端：一根通道上指名线路读写；关掉不放口。"""

from pathlib import Path

from comtee import Comtee, LineHold, UsbIdentity
from comtee.agent import AgentBridge
from tests.test_comtee import FakeSerial, MemoryStore


def test_读写必须指名线路() -> None:
    """操作哪条线路由人当场告知，串通不猜。"""
    hub = _hub()
    bridge = AgentBridge(hub)

    missing_read = bridge.handle({"op": "read"})
    missing_write = bridge.handle({"op": "write", "text": "x"})

    assert missing_read["ok"] is False
    assert "指名" in missing_read["error"]
    assert missing_write["ok"] is False
    assert "指名" in missing_write["error"]


def test_指名线路后能列出状态并读写() -> None:
    """一根通道可对已有线路读写和列出状态。"""
    serial, device, hub = _ready()
    bridge = AgentBridge(hub)
    serial.emit(device, "你好".encode("gbk"))

    listed = bridge.handle({"op": "list"})
    assert listed["ok"] is True
    assert listed["lines"][0]["human_entry"] == 2222
    assert listed["lines"][0]["serial"] == "FT123"
    assert listed["lines"][0]["hold"] == LineHold.HELD
    read = bridge.handle({"op": "read", "human_entry": 2222})
    assert read["ok"] is True
    assert read["text"] == "你好"
    written = bridge.handle({"op": "write", "human_entry": 2222, "text": "ab"})
    assert written["ok"] is True
    assert serial.written(device) == b"ab"


def test_Agent端不能编排或改参数() -> None:
    """MCP 与管道都不得创建、改、拆线路。"""
    hub = _hub()
    bridge = AgentBridge(hub)
    created = bridge.handle({"op": "create_line", "human_entry": 2222})
    changed = bridge.handle({"op": "change_line", "human_entry": 2222})
    removed = bridge.handle({"op": "remove_line", "human_entry": 2222})
    assert created["ok"] is False
    assert "编排" in created["error"]
    assert changed["ok"] is False
    assert "串口参数" in changed["error"]
    assert removed["ok"] is False
    assert "编排" in removed["error"]


def test_关掉Agent端不放口不拆线路() -> None:
    """管道或 MCP 断开只是 Agent 离开，占口和线路还在。"""
    serial, device, hub = _ready()
    bridge = AgentBridge(hub)
    bridge.handle({"op": "read", "human_entry": 2222})
    assert hub.list_lines()[0].agent_connected is True

    bridge.close()

    assert serial.is_held(device)
    assert hub.list_lines()[0].human_entry == 2222
    assert hub.list_lines()[0].agent_connected is False
    assert hub.list_lines()[0].hold == LineHold.HELD


def test_skill禁止直接打开设备并指向Agent端() -> None:
    """skill 写明不要自己开 COM，去连串通的 Agent 端。"""
    text = Path("skills/comtee/SKILL.md").read_text(encoding="utf-8")
    assert "不要自己打开设备" in text or "不要自己打开" in text
    assert "Agent 端" in text
    assert "COM" in text or "串口" in text


def _hub() -> Comtee:
    """假串口上的一份串通。"""
    return _ready()[2]


def _ready() -> tuple[FakeSerial, UsbIdentity, Comtee]:
    """占口后的假设备、线路和串通。"""
    serial = FakeSerial()
    device = UsbIdentity(vid=0x0403, pid=0x6001, serial="FT123")
    serial.plug(device)
    hub = Comtee(serial, MemoryStore())
    hub.create_line(2222, device)
    return serial, device, hub


def test_命名管道指名读写且关掉不放口() -> None:
    """一根命名管道可对已有线路读写；客户端断开不放口。"""
    import os
    import time

    from comtee.agent import AgentPipe, PipeClient

    serial, device, hub = _ready()
    name = rf"\\.\pipe\comtee-test-{os.getpid()}"
    server = AgentPipe(hub, name=name)
    server.start()
    client = None
    try:
        deadline = time.monotonic() + 2.0
        while True:
            try:
                client = PipeClient(name)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        listed = client.call({"op": "list"})
        assert listed["ok"] is True
        assert listed["lines"][0]["human_entry"] == 2222
        serial.emit(device, b"xy")
        read = client.call({"op": "read", "human_entry": 2222})
        assert read["text"] == "xy"
        client.call({"op": "write", "human_entry": 2222, "text": "z"})
        assert serial.written(device) == b"z"
        client.close()
        client = None
        assert serial.is_held(device)
        assert hub.list_lines()[0].human_entry == 2222
    finally:
        if client is not None:
            try:
                client.close()
            except OSError:
                pass
        server.shutdown()
