"""Cursor MCP：stdio 与 Agent 管道之间的翻译，自己不打开设备。"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any

from comtee.agent import PIPE_NAME, PipeClient

_TOOLS = [
    {
        "name": "list_lines",
        "description": "列出串通上已有线路的状态。不看设备字节流。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_line",
        "description": "按人端入口指名读取该线路解码后的字。",
        "inputSchema": {
            "type": "object",
            "properties": {"human_entry": {"type": "integer"}},
            "required": ["human_entry"],
        },
    },
    {
        "name": "write_line",
        "description": "按人端入口指名写入。不能编排线路。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "human_entry": {"type": "integer"},
                "text": {"type": "string"},
            },
            "required": ["human_entry", "text"],
        },
    },
]


def dispatch(message: dict, call: Callable[[dict], dict]) -> dict | None:
    """把 MCP 工具调用翻译成管道请求；不占设备。"""
    method = str(message.get("method", ""))
    rpc_id = message.get("id")
    if method == "initialize":
        return _ok(
            rpc_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "comtee", "version": "0.1.0"},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _ok(rpc_id, {"tools": _TOOLS})
    if method == "tools/call":
        params = message.get("params") or {}
        name = str(params.get("name", ""))
        args = params.get("arguments") or {}
        data = _tool(name, args if isinstance(args, dict) else {}, call)
        return _ok(
            rpc_id,
            {
                "content": [
                    {"type": "text", "text": json.dumps(data, ensure_ascii=False)}
                ]
            },
        )
    if method == "ping":
        return _ok(rpc_id, {})
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {"code": -32601, "message": "未知方法"},
    }


def main() -> None:
    """stdio 循环：只连命名管道，不打开设备、不听 TCP。"""
    client = PipeClient(PIPE_NAME)
    try:
        while True:
            message = _read_rpc(sys.stdin.buffer)
            if message is None:
                return
            reply = dispatch(message, client.call)
            if reply is not None:
                _write_rpc(sys.stdout.buffer, reply)
    finally:
        client.close()


def _tool(name: str, args: dict[str, Any], call: Callable[[dict], dict]) -> dict:
    """把工具名落到指名管道请求。"""
    if name == "list_lines":
        return call({"op": "list"})
    if name == "read_line":
        return call({"op": "read", "human_entry": int(args["human_entry"])})
    if name == "write_line":
        return call(
            {
                "op": "write",
                "human_entry": int(args["human_entry"]),
                "text": str(args.get("text", "")),
            }
        )
    return {"ok": False, "error": "未知工具"}


def _ok(rpc_id: object, result: dict) -> dict:
    """JSON-RPC 成功回复。"""
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def _read_rpc(stream: Any) -> dict | None:
    """读一条 Content-Length 分帧的 JSON-RPC。"""
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        decoded = line.decode("ascii")
        key, value = decoded.split(":", 1)
        headers[key.lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    body = stream.read(length)
    loaded = json.loads(body.decode("utf-8"))
    if isinstance(loaded, dict):
        return loaded
    return None


def _write_rpc(stream: Any, message: dict) -> None:
    """写出一条 Content-Length 分帧的 JSON-RPC。"""
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    stream.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    stream.write(body)
    stream.flush()


if __name__ == "__main__":
    main()
