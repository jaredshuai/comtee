"""源码与安装包的启动命令不同。"""

from comtee.runtime import is_compiled, launch_command


def test_源码自启仍走模块入口() -> None:
    """开发运行要带 -m comtee，才能找到包。"""
    assert (
        launch_command(r"C:\Python\python.exe", compiled=False)
        == r'"C:\Python\python.exe" -m comtee'
    )


def test_安装包自启只跑exe() -> None:
    """Nuitka 编出来的入口就是 exe，再加 -m 会启动失败。"""
    assert (
        launch_command(
            r"C:\Users\jared\AppData\Local\Programs\串通\comtee.exe", compiled=True
        )
        == r'"C:\Users\jared\AppData\Local\Programs\串通\comtee.exe"'
    )


def test_源码运行时不是编译产物() -> None:
    """当前测试进程是解释器，不得被当成安装包。"""
    assert is_compiled() is False
