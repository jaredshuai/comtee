"""占位冒烟：入口模块仍叫 comtee，不启动面板。"""

import comtee


def test_package_name_is_comtee() -> None:
    """包名仍是 comtee，对人说话用串通。"""
    assert comtee.__name__ == "comtee"
