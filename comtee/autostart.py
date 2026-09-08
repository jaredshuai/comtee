"""登录 Win11 后默认自启，面板里可关。"""

from collections.abc import Iterator, MutableMapping

from comtee.persist import UserSettings


class AutoStart:
    """用一份键值表表示启动项；真机接到 HKCU Run。"""

    def __init__(
        self,
        slots: MutableMapping[str, str],
        *,
        name: str,
        command: str,
    ) -> None:
        """slots 是启动项名到命令行。"""
        self._slots = slots
        self._name = name
        self._command = command

    def is_enabled(self) -> bool:
        """启动项是否还在。"""
        return self._name in self._slots

    def set_enabled(self, enabled: bool) -> None:
        """打开或关掉开机自启。"""
        if enabled:
            self._slots[self._name] = self._command
        else:
            self._slots.pop(self._name, None)

    def enable_default(self) -> None:
        """尚未配置时默认打开。"""
        if self._name not in self._slots:
            self.set_enabled(True)


class PreferredAutoStart:
    """Run 键加上写盘偏好：关掉后下次启动仍关。"""

    def __init__(self, autostart: AutoStart, settings: UserSettings) -> None:
        """注入启动项与偏好存档。"""
        self._autostart = autostart
        self._settings = settings

    def apply_on_launch(self) -> None:
        """按偏好同步启动项；从未写过偏好则默认打开并记下。"""
        if not self._settings.has_autostart_preference():
            self._autostart.enable_default()
            self._settings.set_autostart(True)
            return
        self._autostart.set_enabled(self._settings.autostart())

    def is_enabled(self) -> bool:
        """启动项是否还在。"""
        return self._autostart.is_enabled()

    def set_enabled(self, enabled: bool) -> None:
        """同时改启动项和偏好。"""
        self._autostart.set_enabled(enabled)
        self._settings.set_autostart(enabled)


class WinRunKey(MutableMapping[str, str]):
    """HKCU\\...\\Run，给 AutoStart 当 slots。"""

    _PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def __getitem__(self, name: str) -> str:
        """读出一条启动命令。"""
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._PATH) as key:
                value, _ = winreg.QueryValueEx(key, name)
        except OSError as exc:
            raise KeyError(name) from exc
        return str(value)

    def __setitem__(self, name: str, command: str) -> None:
        """写入一条启动命令。"""
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self._PATH) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, command)

    def __delitem__(self, name: str) -> None:
        """删掉一条启动命令。"""
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                self._PATH,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.DeleteValue(key, name)
        except OSError as exc:
            raise KeyError(name) from exc

    def __iter__(self) -> Iterator[str]:
        """遍历启动项名。"""
        return iter(self._names())

    def __len__(self) -> int:
        """启动项数量。"""
        return len(self._names())

    def _names(self) -> list[str]:
        """列出 Run 键下的名字。"""
        import winreg

        names: list[str] = []
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._PATH) as key:
                index = 0
                while True:
                    try:
                        names.append(winreg.EnumValue(key, index)[0])
                    except OSError:
                        break
                    index += 1
        except OSError:
            return []
        return names


def windows_autostart(command: str) -> AutoStart:
    """接到本机登录自启。"""
    return AutoStart(WinRunKey(), name="串通", command=command)
