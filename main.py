def main() -> None:
    """启动串通：单例、托盘常驻、面板编排线路。"""
    from multiprocessing import freeze_support

    freeze_support()
    from comtee.app import run

    run()


if __name__ == "__main__":
    main()
