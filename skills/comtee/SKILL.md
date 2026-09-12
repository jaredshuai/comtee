# 串通 Agent 端

对人说话用「串通」。包名仍是 comtee。

**不要自己打开设备**（不要自己开 COM、不要用 pyserial / USB 串口当设备所有者）。现场哪台设备由人在面板上钉到线路；Agent 只连串通的 **Agent 端**。

## 怎么连

- 串通常驻后，Agent 端是本机命名管道 `\\.\pipe\comtee`（不是 TCP）。
- Cursor 里用 MCP：`python -m comtee.mcp`。MCP 只做 stdio 与管道的翻译，自己不打开设备。
- 关掉 MCP 不会放口、不会拆线路。

## 操作哪条线路

由人当场告知 **人端入口**（本机 Telnet 端口号）。串通不替你猜设备。

可用工具：`list_lines`、`read_line`、`write_line`。不能创建、改、拆线路，也不能改串口参数和 Agent 字符集（解码）。`list_lines` 的 `writable` 表示此刻设备是否可写。设备未占口时 `write_line` 会失败，不会在重连后补发。
