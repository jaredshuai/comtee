"""发版标签必须和 pyproject 版本对上，避免打错包。"""

from pathlib import Path

from comtee.release_tag import (
    main,
    normalize_tag,
    read_project_version,
    versions_match,
)


def test_标签写成标准版本号() -> None:
    """refs 前缀和开头的 v 都不是版本号本身。"""
    assert normalize_tag("refs/tags/v0.1.0") == "0.1.0"
    assert normalize_tag("v1.2.3") == "1.2.3"
    assert normalize_tag("2.0.0") == "2.0.0"


def test_标签与项目版本一致才算匹配() -> None:
    """v0.1.0 对 0.1.0；对不上就不能发。"""
    assert versions_match("v0.1.0", "0.1.0") is True
    assert versions_match("refs/tags/v0.1.0", "0.1.0") is True
    assert versions_match("v0.1.1", "0.1.0") is False


def test_能读出pyproject版本(tmp_path: Path) -> None:
    """发版核对应读同一份 toml，不另写版本号。"""
    path = tmp_path / "pyproject.toml"
    path.write_text('[project]\nname = "demo"\nversion = "3.4.5"\n', encoding="utf-8")
    assert read_project_version(path) == "3.4.5"


def test_命令行对不上则失败(tmp_path: Path) -> None:
    """给 CI 用的入口：不一致返回非零。"""
    path = tmp_path / "pyproject.toml"
    path.write_text('[project]\nname = "demo"\nversion = "0.1.0"\n', encoding="utf-8")
    assert main(["--tag", "v0.1.0", "--pyproject", str(path)]) == 0
    assert main(["--tag", "v0.2.0", "--pyproject", str(path)]) == 1
