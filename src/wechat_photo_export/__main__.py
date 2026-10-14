"""模块和冻结程序共用入口；子进程必须在导入 Qt 之前分流。"""
import multiprocessing
import sys


def main():
    multiprocessing.freeze_support()
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        from .cli import main as cli
        return cli(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        from .selftest import main as selftest
        return selftest()
    from .gui.window import launch
    return launch()


if __name__ == "__main__":
    raise SystemExit(main())
