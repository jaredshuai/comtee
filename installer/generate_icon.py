"""画出串通窗口图标，给 Nuitka 和 Inno Setup 用。"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from comtee.branding import write_icon


def main() -> None:
    """默认写到本脚本旁边的 comtee.ico。"""
    write_icon(Path(__file__).with_name("comtee.ico"))


if __name__ == "__main__":
    main()
