"""编排写盘：串通退出再打开后上一份还在。"""

from pathlib import Path

import pytest

from comtee import BluetoothIdentity, LineArrangement, SerialParams, UsbIdentity
from comtee.persist import FileArrangementStore


def test_写盘后换一个存档实例仍能读回编排(tmp_path: Path) -> None:
    """不把文件名写进串通缝，只通过存档适配器观察。"""
    path = tmp_path / "lines.json"
    device = UsbIdentity(vid=0x0403, pid=0x6001, serial="FT123")
    record = LineArrangement(
        human_entry=2222,
        device=device,
        serial_params=SerialParams(baudrate=115200),
        decode="utf-8",
        name="AC 控制台",
    )
    FileArrangementStore(path).save((record,))
    loaded = FileArrangementStore(path).load()

    assert loaded == (record,)


def test_旧存档没有名称时读成空名称(tmp_path: Path) -> None:
    """名称是后来加上的字段，旧文件仍能恢复线路。"""
    path = tmp_path / "lines.json"
    path.write_text(
        """
        [
          {
            "human_entry": 2222,
            "vid": 1027,
            "pid": 24577,
            "serial": "FT123",
            "baudrate": 9600,
            "data_bits": 8,
            "parity": "N",
            "stop_bits": 1,
            "flow_control": "none",
            "decode": "gbk"
          }
        ]
        """.strip(),
        encoding="utf-8",
    )
    [line] = FileArrangementStore(path).load()
    assert line.name == ""
    assert line.human_entry == 2222


def test_蓝牙线路写盘后仍按BTHENUM身份恢复(tmp_path: Path) -> None:
    """蓝牙线路存档不依赖此刻的 COM 号。"""
    path = tmp_path / "lines.json"
    device = BluetoothIdentity(
        hwid=(
            "BTHENUM\\{00001101-0000-1000-8000-00805F9B34FB}_LOCALMFG&0046\\"
            "8&2ECCB597&0&04220520037B_C00000000"
        )
    )
    record = LineArrangement(
        human_entry=2222,
        device=device,
        serial_params=SerialParams(),
        decode="gbk",
        name="蓝牙控制台",
    )

    FileArrangementStore(path).save((record,))

    assert FileArrangementStore(path).load() == (record,)


def test_未知设备类型读盘时明确报错(tmp_path: Path) -> None:
    """未知 device_type 不能落入 USB 解析抛 KeyError，而应显式 ValueError。"""
    path = tmp_path / "lines.json"
    path.write_text(
        """
        [
          {
            "human_entry": 2222,
            "device_type": "tcp",
            "baudrate": 9600,
            "data_bits": 8,
            "parity": "N",
            "stop_bits": 1,
            "flow_control": "none",
            "decode": "gbk"
          }
        ]
        """.strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="不支持的设备类型"):
        FileArrangementStore(path).load()
