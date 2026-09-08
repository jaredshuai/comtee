"""Agent 端：全进程一根通道，读写必须指名线路。"""

from __future__ import annotations

import json
import threading
from typing import Any

from comtee.hub import Agent, AgentForbidden, Comtee, LineStatus

PIPE_NAME = r"\\.\pipe\comtee"


class AgentBridge:
    """把指名请求落到已有线路上；关掉只离开，不放口、不拆线路。"""

    def __init__(self, hub: Comtee) -> None:
        """注入串通；不打开设备。"""
        self._hub = hub
        self._agents: dict[int, Agent] = {}

    def handle(self, request: dict) -> dict:
        """处理一条指名请求。"""
        op = str(request.get("op", ""))
        if op == "list":
            return {
                "ok": True,
                "lines": [_line_view(line) for line in self._hub.list_lines()],
            }
        if op in {"create_line", "remove_line"}:
            return {"ok": False, "error": "Agent 不能编排线路"}
        if op == "change_line":
            return {"ok": False, "error": "Agent 不能改串口参数和解码"}
        if op in {"read", "write"} and "human_entry" not in request:
            return {"ok": False, "error": "必须指名线路"}
        if op == "read":
            return self._read(int(request["human_entry"]))
        if op == "write":
            return self._write(
                int(request["human_entry"]), str(request.get("text", ""))
            )
        return {"ok": False, "error": "未知操作"}

    def close(self) -> None:
        """Agent 离开所有线路；不放口、不拆编排。"""
        for agent in self._agents.values():
            agent.leave()
        self._agents.clear()

    def _agent(self, human_entry: int) -> Agent:
        """拿到指名线路上的 Agent；没有则进场。"""
        existing = self._agents.get(human_entry)
        if existing is not None:
            return existing
        agent = self._hub.attach_agent(human_entry)
        self._agents[human_entry] = agent
        return agent

    def _read(self, human_entry: int) -> dict:
        """读出该线路解码后的字。"""
        try:
            text = self._agent(human_entry).received()
        except KeyError:
            return {"ok": False, "error": "没有这条线路"}
        except AgentForbidden as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "text": text}

    def _write(self, human_entry: int, text: str) -> dict:
        """按该线路解码把字写成原字节打进去。"""
        try:
            decode = self._decode_of(human_entry)
            self._agent(human_entry).write(text.encode(decode, errors="replace"))
        except KeyError:
            return {"ok": False, "error": "没有这条线路"}
        except AgentForbidden as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    def _decode_of(self, human_entry: int) -> str:
        """指名线路当前的解码。"""
        for line in self._hub.list_lines():
            if line.human_entry == human_entry:
                return line.decode
        raise KeyError(human_entry)


def _line_view(line: LineStatus) -> dict:
    """列出状态时不带设备字节。"""
    return {
        "human_entry": line.human_entry,
        "vid": line.device.vid,
        "pid": line.device.pid,
        "serial": line.device.serial,
        "hold": line.hold,
        "decode": line.decode,
        "human_clients": line.human_clients,
        "agent_connected": line.agent_connected,
    }


_PIPE_ACCESS_DUPLEX = 0x00000003
_PIPE_TYPE_BYTE = 0x00000000
_PIPE_READMODE_BYTE = 0x00000000
_PIPE_WAIT = 0x00000000
_PIPE_REJECT_REMOTE = 0x00000008
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_OPEN_EXISTING = 3
_FILE_SHARE_READ = 1
_FILE_SHARE_WRITE = 2
_INVALID_HANDLE = 0xFFFFFFFFFFFFFFFF
_ERROR_PIPE_CONNECTED = 535
_NMPWAIT = 2000


def _kernel32() -> Any:
    """Windows 管道 API。"""
    import ctypes
    from ctypes import wintypes

    dll = ctypes.WinDLL("kernel32", use_last_error=True)
    dll.CreateNamedPipeW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
    ]
    dll.CreateNamedPipeW.restype = wintypes.HANDLE
    dll.ConnectNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
    dll.ConnectNamedPipe.restype = wintypes.BOOL
    dll.DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
    dll.DisconnectNamedPipe.restype = wintypes.BOOL
    dll.ReadFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    dll.ReadFile.restype = wintypes.BOOL
    dll.WriteFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    dll.WriteFile.restype = wintypes.BOOL
    dll.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    dll.CreateFileW.restype = wintypes.HANDLE
    dll.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    dll.WaitNamedPipeW.restype = wintypes.BOOL
    dll.CloseHandle.argtypes = [wintypes.HANDLE]
    dll.CloseHandle.restype = wintypes.BOOL
    return dll


class AgentPipe:
    """本机一根命名管道；不为 Agent 再开 TCP。"""

    def __init__(self, hub: Comtee, name: str = PIPE_NAME) -> None:
        """name 是 Windows 管道路径。"""
        self._hub = hub
        self._name = name
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """后台听 Agent 端。"""
        self._thread = threading.Thread(target=self.serve, daemon=True)
        self._thread.start()

    def serve(self) -> None:
        """循环接上客户端；断开后 Agent 离开，不放口。"""
        k32 = _kernel32()
        while not self._stop.is_set():
            handle = k32.CreateNamedPipeW(
                self._name,
                _PIPE_ACCESS_DUPLEX,
                _PIPE_TYPE_BYTE
                | _PIPE_READMODE_BYTE
                | _PIPE_WAIT
                | _PIPE_REJECT_REMOTE,
                1,
                65536,
                65536,
                0,
                None,
            )
            if handle == _INVALID_HANDLE or not handle:
                if self._stop.is_set():
                    return
                continue
            connected = k32.ConnectNamedPipe(handle, None)
            if not connected:
                import ctypes

                if ctypes.get_last_error() != _ERROR_PIPE_CONNECTED:
                    k32.CloseHandle(handle)
                    continue
            if self._stop.is_set():
                k32.DisconnectNamedPipe(handle)
                k32.CloseHandle(handle)
                return
            self._session(int(handle))
            k32.DisconnectNamedPipe(handle)
            k32.CloseHandle(handle)

    def shutdown(self) -> None:
        """停听；唤醒可能堵在 ConnectNamedPipe 上的线程。"""
        self._stop.set()
        try:
            PipeClient(self._name).close()
        except OSError:
            pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _session(self, handle: int) -> None:
        """一条管道连接对应一次 Agent 进场，断线则离开。"""
        bridge = AgentBridge(self._hub)
        leftover = bytearray()
        try:
            while not self._stop.is_set():
                request = _read_json(handle, leftover)
                if request is None:
                    return
                _write_json(handle, bridge.handle(request))
        finally:
            bridge.close()


class PipeClient:
    """MCP 用来连 Agent 管道的客户端，自己不打开设备。"""

    def __init__(self, name: str = PIPE_NAME) -> None:
        """连上已有的串通管道。"""
        k32 = _kernel32()
        k32.WaitNamedPipeW(name, _NMPWAIT)
        handle = k32.CreateFileW(
            name,
            _GENERIC_READ | _GENERIC_WRITE,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE,
            None,
            _OPEN_EXISTING,
            0,
            None,
        )
        if handle == _INVALID_HANDLE or not handle:
            raise OSError("连不上串通 Agent 端")
        self._handle = int(handle)
        self._buf = bytearray()

    def call(self, request: dict) -> dict:
        """发一条指名请求并等回复。"""
        _write_json(self._handle, request)
        result = _read_json(self._handle, self._buf)
        if result is None:
            raise OSError("Agent 端断开")
        return result

    def close(self) -> None:
        """断开管道，不放口、不拆线路。"""
        _kernel32().CloseHandle(self._handle)


def _write_json(handle: int, payload: dict) -> None:
    """写出一行 JSON。"""
    import ctypes
    from ctypes import wintypes

    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
    written = wintypes.DWORD(0)
    ok = _kernel32().WriteFile(handle, raw, len(raw), ctypes.byref(written), None)
    if not ok:
        raise OSError("写入 Agent 管道失败")


def _read_json(handle: int, buf: bytearray) -> dict | None:
    """读入一行 JSON；对端关闭则空。"""
    import ctypes
    from ctypes import wintypes

    k32 = _kernel32()
    while True:
        newline = buf.find(b"\n")
        if newline >= 0:
            line = bytes(buf[:newline])
            del buf[: newline + 1]
            if not line:
                continue
            loaded = json.loads(line.decode("utf-8"))
            if isinstance(loaded, dict):
                return loaded
            return None
        chunk = ctypes.create_string_buffer(4096)
        got = wintypes.DWORD(0)
        ok = k32.ReadFile(handle, chunk, 4096, ctypes.byref(got), None)
        if not ok or got.value == 0:
            return None
        buf.extend(chunk.raw[: got.value])
