"""线路设置的可测层：校验、串口格式和保存影响说明。"""

from comtee.hub import LineHold, SerialParams
from comtee.line_edit import (
    ALLOWED_CHARSETS,
    ALLOWED_DATA_BITS,
    ALLOWED_FLOW,
    ALLOWED_PARITY,
    ALLOWED_STOP_BITS,
    Draft,
    LineView,
    agent_share_text,
    impact_text,
    serial_format,
    split_status,
    validate_draft,
)


def test_串口格式由实际参数生成() -> None:
    """8N1 不是写死的标签，7E2 必须跟配置走。"""
    assert serial_format(SerialParams()) == "8N1"
    assert (
        serial_format(
            SerialParams(data_bits=7, parity="E", stop_bits=2, flow_control="rtscts")
        )
        == "7E2"
    )


def test_只提供适配器支持的选项() -> None:
    """面板不得提供打不开的数据位、校验、停止位或流控。"""
    assert ALLOWED_DATA_BITS == (5, 6, 7, 8)
    assert ALLOWED_PARITY == ("N", "E", "O")
    assert ALLOWED_STOP_BITS == (1, 2)
    assert ALLOWED_FLOW == ("none", "rtscts", "xonxoff", "dsrdtr")
    assert ALLOWED_CHARSETS == ("gbk", "utf-8")


def test_端口和波特率范围无效时保留字段名() -> None:
    """非法输入就地指出字段，不悄悄改成默认值。"""
    port = validate_draft(_draft(port=0))
    baud = validate_draft(_draft(baud=0))
    assert port is not None and port.field == "port"
    assert baud is not None and baud.field == "baud"


def test_改入口与改参数的影响说明可区分() -> None:
    """保存按钮旁要说清会不会断开人端、会不会重开串口。"""
    current = _view()
    port_change = impact_text(current, _draft(port=3333), creating=False)
    decode_only = impact_text(current, _draft(), creating=False)
    assert "入口" in port_change.message
    assert port_change.warning is True
    assert "不重新打开串口" in decode_only.message
    assert decode_only.warning is False


def test_人端监听和设备占口分开呈现() -> None:
    """Agent 已连接不等于整条链路可写。"""
    held = split_status(_view())
    waiting = split_status(_view(hold=LineHold.WAITING, human_listening=True))
    entry = split_status(_view(human_listening=False))
    assert held.badge == "占口"
    assert "监听" in held.human
    assert "已占口" in held.device
    assert waiting.badge == "等待设备"
    assert "未接入" in waiting.device
    assert entry.badge == "入口端口被占用"
    assert "未监听" in entry.human


def test_Agent说明指名入口并禁止直接开COM() -> None:
    """复制给 Agent 的说明必须带端口，且禁止编排。"""
    text = agent_share_text(_view(name="AC 控制台"))
    assert "2222" in text
    assert "AC 控制台" in text
    assert "list_lines" in text
    assert "不要直接打开 COM" in text


def _draft(*, port: int = 2222, baud: int = 9600) -> Draft:
    """一份合法草稿，测试里只改要看的字段。"""
    return Draft(
        name="AC 控制台",
        port=port,
        baud=baud,
        data_bits=8,
        parity="N",
        stop_bits=1,
        flow_control="none",
        decode="gbk",
        device_key="0403:6001|FT123",
    )


def _view(
    *,
    hold: LineHold = LineHold.HELD,
    human_listening: bool = True,
    name: str = "AC 控制台",
) -> LineView:
    """当前线路的只读视图，给影响说明和状态文案用。"""
    return LineView(
        human_entry=2222,
        name=name,
        hold=hold,
        human_listening=human_listening,
        human_clients=2,
        agent_connected=True,
        serial_params=SerialParams(),
        decode="gbk",
        device_key="0403:6001|FT123",
        device_path="COM6",
    )
