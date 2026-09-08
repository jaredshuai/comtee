"""本机只跑一份串通：用命名互斥量占住这份进程。"""

import ctypes
from ctypes import wintypes

_ERROR_ALREADY_EXISTS = 183
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.argtypes = [
    wintypes.LPVOID,
    wintypes.BOOL,
    wintypes.LPCWSTR,
]
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
_kernel32.ReleaseMutex.restype = wintypes.BOOL


class InstanceLock:
    """占住 Local\\ 下的一把锁；第二份 acquire 失败。"""

    def __init__(self, name: str) -> None:
        """name 是锁的短名，不含 Local\\ 前缀。"""
        self._name = rf"Local\{name}"
        self._handle: int | None = None

    def acquire(self) -> bool:
        """占到返回 True；已有一份则 False。"""
        ctypes.set_last_error(0)
        handle = _kernel32.CreateMutexW(None, True, self._name)
        if not handle:
            return False
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            _kernel32.CloseHandle(handle)
            return False
        self._handle = int(handle)
        return True

    def release(self) -> None:
        """放掉这把锁。"""
        if self._handle is None:
            return
        _kernel32.ReleaseMutex(self._handle)
        _kernel32.CloseHandle(self._handle)
        self._handle = None
