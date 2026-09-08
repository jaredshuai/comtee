"""线路编排写盘，串通启动时恢复上一份；面板偏好另存。"""

import json
from pathlib import Path

from comtee.hub import LineArrangement, SerialParams, UsbIdentity


class FileArrangementStore:
    """一份 JSON 存档，v1 不做多套配置档。"""

    def __init__(self, path: Path) -> None:
        """指定存档路径。"""
        self._path = path

    def load(self) -> tuple[LineArrangement, ...]:
        """读出上一份编排；没有文件则空。"""
        if not self._path.is_file():
            return ()
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        return tuple(_from_dict(item) for item in raw)

    def save(self, lines: tuple[LineArrangement, ...]) -> None:
        """写入当前编排。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = [_to_dict(line) for line in lines]
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class UserSettings:
    """面板偏好：自启是否打开。与线路存档分开，关掉自启不能当成「尚未配置」。"""

    def __init__(self, path: Path) -> None:
        """指定偏好文件路径。"""
        self._path = path

    def has_autostart_preference(self) -> bool:
        """是否已经写过自启偏好。"""
        return "autostart" in self._load()

    def autostart(self) -> bool:
        """读出自启偏好；从未写过则视为默认打开。"""
        return bool(self._load().get("autostart", True))

    def set_autostart(self, enabled: bool) -> None:
        """写下自启偏好。"""
        data = self._load()
        data["autostart"] = enabled
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load(self) -> dict:
        """读出偏好字典；没有文件则空。"""
        if not self._path.is_file():
            return {}
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        return raw


def _to_dict(line: LineArrangement) -> dict:
    """把一条编排变成可写盘的字典。"""
    return {
        "human_entry": line.human_entry,
        "vid": line.device.vid,
        "pid": line.device.pid,
        "serial": line.device.serial,
        "baudrate": line.serial_params.baudrate,
        "data_bits": line.serial_params.data_bits,
        "parity": line.serial_params.parity,
        "stop_bits": line.serial_params.stop_bits,
        "flow_control": line.serial_params.flow_control,
        "decode": line.decode,
    }


def _from_dict(item: dict) -> LineArrangement:
    """从存档字典恢复一条编排。"""
    return LineArrangement(
        human_entry=int(item["human_entry"]),
        device=UsbIdentity(
            vid=int(item["vid"]),
            pid=int(item["pid"]),
            serial=str(item["serial"]),
        ),
        serial_params=SerialParams(
            baudrate=int(item["baudrate"]),
            data_bits=int(item["data_bits"]),
            parity=str(item["parity"]),
            stop_bits=int(item["stop_bits"]),
            flow_control=str(item["flow_control"]),
        ),
        decode=str(item["decode"]),
    )
