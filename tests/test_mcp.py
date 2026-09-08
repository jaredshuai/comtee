"""MCP 只翻译到 Agent 管道，不打开设备。"""

from io import BytesIO
from pathlib import Path

from comtee.mcp import _read_rpc, _write_rpc, dispatch


def test_mcp工具调用必须指名线路() -> None:
    """read_line / write_line 把人端入口交给管道。"""
    seen: list[dict] = []

    def call(request: dict) -> dict:
        """记下翻译后的管道请求。"""
        seen.append(request)
        return {"ok": True, "text": ""}

    reply = dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "read_line",
                "arguments": {"human_entry": 2222},
            },
        },
        call,
    )
    written = dispatch(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "write_line",
                "arguments": {"human_entry": 2222, "text": "ab"},
            },
        },
        call,
    )
    assert reply is not None
    assert written is not None
    assert seen == [
        {"op": "read", "human_entry": 2222},
        {"op": "write", "human_entry": 2222, "text": "ab"},
    ]


def test_mcp列出线路不编排() -> None:
    """list_lines 只问状态；没有 create_line 工具。"""
    calls: list[dict] = []

    def call(request: dict) -> dict:
        """记下管道请求。"""
        calls.append(request)
        return {"ok": True, "lines": []}

    listed = dispatch({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, call)
    init = dispatch({"jsonrpc": "2.0", "id": 3, "method": "initialize"}, call)
    dispatch(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "list_lines", "arguments": {}},
        },
        call,
    )
    assert listed is not None
    names = [tool["name"] for tool in listed["result"]["tools"]]
    assert names == ["list_lines", "read_line", "write_line"]
    assert "create_line" not in names
    assert "change_line" not in names
    assert init is not None
    assert init["result"]["serverInfo"]["name"] == "comtee"
    assert calls == [{"op": "list"}]


def test_mcp源码不打开设备也不听TCP() -> None:
    """MCP 进程不得占设备、不得再开 TCP。"""
    text = Path("comtee/mcp.py").read_text(encoding="utf-8")
    assert "usb_serial" not in text
    assert "windows_usb_serial" not in text
    assert "listen(" not in text
    assert "bind(" not in text


def test_mcp分帧读写() -> None:
    """stdio 用 Content-Length，不是再开一个 TCP 口。"""
    buf = BytesIO()
    _write_rpc(buf, {"jsonrpc": "2.0", "id": 1, "method": "ping"})
    buf.seek(0)
    message = _read_rpc(buf)
    assert message == {"jsonrpc": "2.0", "id": 1, "method": "ping"}
