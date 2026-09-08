"""标准 Telnet：协商留在人端入口，不进设备。"""

import socket
import threading
from typing import Any

IAC = 255
DONT = 254
DO = 253
WONT = 252
WILL = 251
SB = 250
SE = 240
NOP = 241
BINARY = 0
ECHO = 1
SGA = 3

_ACCEPT = frozenset({BINARY, SGA})


class TelnetFilter:
    """把套接字字节里的 Telnet 协商剥掉，只留下应进设备的原字节。"""

    def __init__(self) -> None:
        """新建一条 Telnet 会话的过滤状态。"""
        self._buf = bytearray()
        self._replies = bytearray()
        self._mode = "data"
        self._cmd = 0
        self._sent: set[tuple[int, int]] = set()

    def greet(self) -> bytes:
        """进场时声明：二进制、抑制 GA、不本地回显。"""
        self._sent.add((WILL, SGA))
        self._sent.add((DO, SGA))
        self._sent.add((WILL, BINARY))
        self._sent.add((DO, BINARY))
        self._sent.add((WONT, ECHO))
        return bytes(
            [
                IAC,
                WILL,
                SGA,
                IAC,
                DO,
                SGA,
                IAC,
                WILL,
                BINARY,
                IAC,
                DO,
                BINARY,
                IAC,
                WONT,
                ECHO,
            ]
        )

    def ingest(self, chunk: bytes) -> bytes:
        """吃进套接字字节，吐出应写入设备的应用数据。"""
        self._buf.extend(chunk)
        payload = bytearray()
        while self._buf:
            byte = self._buf[0]
            if self._mode == "data":
                self._buf.pop(0)
                if byte == IAC:
                    self._mode = "iac"
                else:
                    payload.append(byte)
            elif self._mode == "iac":
                self._buf.pop(0)
                if byte == IAC:
                    payload.append(IAC)
                    self._mode = "data"
                elif byte in (WILL, WONT, DO, DONT):
                    self._cmd = byte
                    self._mode = "option"
                elif byte == SB:
                    self._mode = "sub"
                elif byte == NOP:
                    self._mode = "data"
                else:
                    self._mode = "data"
            elif self._mode == "option":
                if not self._buf:
                    break
                option = self._buf.pop(0)
                self._answer(self._cmd, option)
                self._mode = "data"
            elif self._mode == "sub":
                self._buf.pop(0)
                if byte == IAC:
                    self._mode = "sub_iac"
            elif self._mode == "sub_iac":
                self._buf.pop(0)
                if byte == SE:
                    self._mode = "data"
                elif byte != IAC:
                    self._mode = "sub"
        return bytes(payload)

    def replies(self) -> bytes:
        """取出应对方的协商回复。"""
        data = bytes(self._replies)
        self._replies.clear()
        return data

    def encode(self, payload: bytes) -> bytes:
        """设备字节打到 Telnet 时，255 要写成 IAC IAC。"""
        return payload.replace(bytes([IAC]), bytes([IAC, IAC]))

    def _answer(self, command: int, option: int) -> None:
        """对 WILL/DO 给出接受或拒绝；已声明过的选项不再回，避免打环。"""
        if command == DO:
            reply = WILL if option in _ACCEPT else WONT
        elif command == WILL:
            reply = DO if option in _ACCEPT else DONT
        else:
            return
        key = (reply, option)
        if key in self._sent:
            return
        self._sent.add(key)
        self._replies.extend((IAC, reply, option))


class TelnetEntries:
    """在 127.0.0.1 上听各条线路的人端入口。"""

    def __init__(self) -> None:
        """只绑 127.0.0.1。"""
        self._hub: Any = None
        self._servers: dict[int, _Listener] = {}

    def attach(self, hub: Any) -> None:
        """接到串通，连上后挂客户端。"""
        self._hub = hub

    def occupy(self, human_entry: int) -> bool:
        """开始听该人端入口；端口被占则不听并返回 False。"""
        if human_entry in self._servers:
            return True
        try:
            listener = _Listener("127.0.0.1", human_entry, self._hub)
        except OSError:
            return False
        listener.start()
        self._servers[human_entry] = listener
        return True

    def release(self, human_entry: int) -> None:
        """停掉该人端入口并断开已连上的 Telnet。"""
        listener = self._servers.pop(human_entry, None)
        if listener is not None:
            listener.close()

    def shutdown(self) -> None:
        """关掉全部人端入口。"""
        for port in list(self._servers):
            self.release(port)

    def listen_address(self, human_entry: int) -> tuple[str, int]:
        """此刻绑着的地址，给测试确认只绑回环。"""
        host, port = self._servers[human_entry].address()
        return host, port


class _Listener:
    """一条人端入口上的听端口。"""

    def __init__(self, host: str, port: int, hub: Any) -> None:
        """绑回环并准备接受多个 Telnet。"""
        self._hub = hub
        self._stop = threading.Event()
        self._pumps: list[_Pump] = []
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        self._sock.bind((host, port))
        self._sock.listen(8)
        self._sock.settimeout(0.2)
        self._thread = threading.Thread(target=self._accept, daemon=True)

    def start(self) -> None:
        """开始接受连接。"""
        self._thread.start()

    def address(self) -> tuple[str, int]:
        """套接字绑着的主机和端口。"""
        host, port = self._sock.getsockname()[:2]
        return str(host), int(port)

    def close(self) -> None:
        """停听并断开本入口上的 Telnet。"""
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass
        for pump in list(self._pumps):
            pump.close()
        self._thread.join(timeout=2.0)

    def _accept(self) -> None:
        """接受多个 Telnet 客户端。"""
        while not self._stop.is_set():
            try:
                conn, _addr = self._sock.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            pump = _Pump(conn, self._hub, self._sock.getsockname()[1])
            self._pumps.append(pump)
            pump.start()


class _Pump:
    """一个 Telnet 套接字与一条线路上的客户端之间泵字节。"""

    def __init__(self, conn: Any, hub: Any, human_entry: int) -> None:
        """挂上线路并准备读写。"""
        self._conn = conn
        self._hub = hub
        self._human_entry = human_entry
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        """开始泵字节。"""
        self._thread.start()

    def close(self) -> None:
        """断开这个 Telnet。"""
        self._stop.set()
        try:
            self._conn.close()
        except OSError:
            pass
        self._thread.join(timeout=2.0)

    def _run(self) -> None:
        """协商留在套接字上，应用数据进线路。"""
        client = self._hub.attach_client(self._human_entry)
        session = TelnetFilter()
        self._conn.settimeout(0.05)
        try:
            self._conn.sendall(session.greet())
            while not self._stop.is_set():
                chunk = b""
                try:
                    chunk = self._conn.recv(4096)
                except TimeoutError:
                    chunk = None
                except OSError:
                    break
                if chunk == b"":
                    break
                if chunk:
                    payload = session.ingest(chunk)
                    reply = session.replies()
                    if reply:
                        self._conn.sendall(reply)
                    if payload:
                        client.write(payload)
                outgoing = client.received()
                if outgoing:
                    self._conn.sendall(session.encode(outgoing))
        finally:
            client.leave()
            try:
                self._conn.close()
            except OSError:
                pass
