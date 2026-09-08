"""编排写盘：串通退出再打开后上一份还在。"""

from pathlib import Path

from comtee import LineArrangement, SerialParams, UsbIdentity
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
    )
    FileArrangementStore(path).save((record,))
    loaded = FileArrangementStore(path).load()

    assert loaded == (record,)
