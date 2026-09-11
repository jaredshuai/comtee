"""python -m comtee 入口。"""

from multiprocessing import freeze_support

from comtee.app import run

if __name__ == "__main__":
    freeze_support()
    run()
