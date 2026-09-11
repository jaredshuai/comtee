"""核对发版标签和 pyproject 版本是同一号。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def normalize_tag(ref: str) -> str:
    """把 refs/tags/v1.2.3 或 v1.2.3 收成 1.2.3。"""
    name = ref.strip()
    name = name.removeprefix("refs/tags/")
    return name.removeprefix("v")


def read_project_version(pyproject: Path) -> str:
    """读 pyproject.toml 里的 project.version。"""
    import tomllib

    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return str(data["project"]["version"]).strip()


def versions_match(tag_ref: str, project_version: str) -> bool:
    """标签去掉 v 之后必须和项目版本相同。"""
    return normalize_tag(tag_ref) == project_version.strip()


def main(argv: list[str] | None = None) -> int:
    """CI 里核对 git 标签与 pyproject，对不上就失败。"""
    parser = argparse.ArgumentParser(
        description="Check that a git tag matches pyproject version."
    )
    parser.add_argument("--tag", required=True, help="refs/tags/vX.Y.Z or vX.Y.Z")
    parser.add_argument(
        "--pyproject",
        default=str(Path(__file__).resolve().parents[1] / "pyproject.toml"),
        help="Path to pyproject.toml",
    )
    args = parser.parse_args(argv)
    project = read_project_version(Path(args.pyproject))
    if not versions_match(args.tag, project):
        print(
            f"tag {args.tag!r} != project version {project!r}",
            file=sys.stderr,
        )
        return 1
    print(f"tag {normalize_tag(args.tag)} matches project {project}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
