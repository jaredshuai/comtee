"""人端 Telnet：协商不进设备，回环上可多连。"""

import socket
import time
from collections.abc import Callable

import pytest

from comtee import Comtee, HumanEntryOccupied, LineHold
from comtee.telnet import TelnetEntries, TelnetFilter
from tests.test_comtee import FakeSerial, MemoryStore, _plugged


def test_telnet协商字节不进设备() -> None:
    """IAC 协商是 Telnet 自己的，不能当成串口字节。"""
    session = TelnetFilter()
    inbound = bytes([255, 253, 1, 255, 251, 3]) + b"abc"

    payload = session.ingest(inbound)

    assert payload == b"abc"
    replies = session.replies()
    assert 255 in replies
    assert b"abc" not in replies


def test_设备里的255打到telnet要写成IAC_IAC() -> None:
    """二进制串口会打出 0xFF，Telnet 必须转义，否则被当成协商。"""
    assert TelnetFilter().encode(b"\xffOK") == b"\xff\xffOK"


def test_回环telnet能看见设备字节且协商不进设备() -> None:
    """连 127.0.0.1:人端入口，看见该线路设备字节；IAC 不进设备。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    human = TelnetEntries()
    hub = Comtee(serial, MemoryStore(), human=human)
    port = _free_loopback_port()
    hub.create_line(port, device)
    client = TelnetFilter()
    try:
        sock = _connect(port)
        _read_until_idle(sock, client)
        sock.sendall(bytes([255, 253, 1]) + b"hi")
        _wait_until(lambda: serial.written(device) == b"hi")
        serial.emit(device, b"dev")
        assert _read_app(sock, client) == b"dev"
        host, bound = human.listen_address(port)
        assert host == "127.0.0.1"
        assert bound == port
    finally:
        human.shutdown()


def test_同一入口两个telnet都能看见都能写() -> None:
    """同一人端入口可挂多个标准 Telnet。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    human = TelnetEntries()
    hub = Comtee(serial, MemoryStore(), human=human)
    port = _free_loopback_port()
    hub.create_line(port, device)
    a_filter, b_filter = TelnetFilter(), TelnetFilter()
    try:
        first = _connect(port)
        second = _connect(port)
        _read_until_idle(first, a_filter)
        _read_until_idle(second, b_filter)
        first.sendall(b"one")
        _wait_until(lambda: serial.written(device) == b"one")
        assert _read_app(second, b_filter) == b"one"
        second.sendall(b"two")
        _wait_until(lambda: serial.written(device) == b"onetwo")
        assert _read_app(first, a_filter) == b"two"
        serial.emit(device, b"both")
        assert _read_app(first, a_filter) == b"both"
        assert _read_app(second, b_filter) == b"both"
    finally:
        human.shutdown()


def test_等待设备时已有telnet不断开设备回来后字节恢复() -> None:
    """USB 不在时人端入口继续听，已连着的 Telnet 不断开。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    human = TelnetEntries()
    hub = Comtee(serial, MemoryStore(), human=human)
    port = _free_loopback_port()
    hub.create_line(port, device)
    session = TelnetFilter()
    try:
        sock = _connect(port)
        _read_until_idle(sock, session)
        serial.unplug(device)
        serial.emit(device, b"gone")
        assert _read_app(sock, session, timeout=0.3) == b""
        serial.plug(device)
        serial.emit(device, b"back")
        assert _read_app(sock, session) == b"back"
    finally:
        human.shutdown()


def test_进场后同一选项不再回以免打环() -> None:
    """已经 WILL/DO 过的选项，对端再 DO/WILL 时不重复答应。"""
    session = TelnetFilter()
    session.greet()
    session.ingest(bytes([255, 253, 3, 255, 251, 3]))
    assert session.replies() == b""


def test_创建线路时入口被占则不留下半条线路() -> None:
    """绑不上人端入口时，交互创建必须回滚，设备不得被这条未建成的线路占用。"""
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    port = int(blocker.getsockname()[1])
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    human = TelnetEntries()
    hub = Comtee(serial, MemoryStore(), human=human)
    try:
        with pytest.raises(HumanEntryOccupied):
            hub.create_line(port, device)
        assert hub.list_lines() == ()
        assert not serial.is_held(device)
        sock = socket.create_connection(("127.0.0.1", port), timeout=0.5)
        sock.sendall(b"not-telnet")
        time.sleep(0.1)
        assert serial.written(device) == b""
        sock.close()
    finally:
        blocker.close()
        human.shutdown()


def test_恢复编排时入口被占线路仍在且未监听() -> None:
    """启动恢复时入口冲突只影响人端监听，不拆线路、不放设备。"""
    store = MemoryStore()
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    first_human = TelnetEntries()
    hub = Comtee(serial, store, human=first_human)
    port = _free_loopback_port()
    hub.create_line(port, device)
    hub.shutdown()
    first_human.shutdown()
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", port))
    blocker.listen(1)
    restored_serial = FakeSerial()
    restored_serial.plug(device)
    restored_human = TelnetEntries()
    try:
        restored = Comtee(restored_serial, store, human=restored_human)
        [line] = restored.list_lines()
        assert line.human_entry == port
        assert line.human_listening is False
        assert line.hold == LineHold.HELD
        with pytest.raises(KeyError):
            restored_human.listen_address(port)
    finally:
        blocker.close()
        restored_human.shutdown()


def test_拆线路后入口停听() -> None:
    """拆掉线路则人端入口不再听。"""
    serial = FakeSerial()
    device = _plugged(serial, "FT123")
    human = TelnetEntries()
    hub = Comtee(serial, MemoryStore(), human=human)
    port = _free_loopback_port()
    hub.create_line(port, device)
    sock = _connect(port)
    try:
        hub.remove_line(port)
        assert hub.list_lines() == ()
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", port))
        probe.close()
    finally:
        sock.close()
        human.shutdown()


def _free_loopback_port() -> int:
    """要一个此刻空闲的回环端口当人端入口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _connect(port: int) -> socket.socket:
    """连上本机人端入口。"""
    deadline = time.monotonic() + 2.0
    last: OSError | None = None
    while time.monotonic() < deadline:
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=0.2)
        except OSError as exc:
            last = exc
            time.sleep(0.02)
    assert last is not None
    raise last


def _read_until_idle(sock: socket.socket, session: TelnetFilter) -> None:
    """吃掉进场协商，不把它们当成设备字节。"""
    session.ingest(_recv_some(sock, timeout=0.4))
    session.replies()


def _read_app(
    sock: socket.socket, session: TelnetFilter, timeout: float = 1.0
) -> bytes:
    """读到一段应用数据；超时则空。"""
    deadline = time.monotonic() + timeout
    got = bytearray()
    while time.monotonic() < deadline:
        chunk = _recv_some(sock, timeout=0.1)
        if chunk:
            got.extend(session.ingest(chunk))
            if got:
                return bytes(got)
    return bytes(got)


def _recv_some(sock: socket.socket, timeout: float) -> bytes:
    """读一段套接字字节，超时则空。"""
    sock.settimeout(timeout)
    try:
        return sock.recv(4096) or b""
    except TimeoutError:
        return b""
    except OSError:
        return b""


def _wait_until(ok: Callable[[], bool], timeout: float = 1.5) -> None:
    """等到条件成立。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ok():
            return
        time.sleep(0.02)
    raise AssertionError("条件一直不成立")
