"""本机只跑一份串通：第二份占不到同一把锁。"""

from comtee.singleton import InstanceLock


def test_第二份占不到同一把锁() -> None:
    """已有一份在跑时，后来者不得假装自己是那一份。"""
    name = "comtee-test-instance-lock"
    first = InstanceLock(name)
    second = InstanceLock(name)
    assert first.acquire() is True
    try:
        assert second.acquire() is False
    finally:
        first.release()
        assert second.acquire() is True
        second.release()
