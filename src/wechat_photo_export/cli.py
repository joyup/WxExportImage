"""可自动化的公共服务入口；绝不把密钥输出到终端。"""
import argparse
import signal
import threading

from .core.errors import MESSAGES, error_code
from .core.selection import select_sessions
from .services.accounts import account_at, discover_accounts
from .services.catalog import refresh_names, sessions
from .services.jobs import build_plan, export
from .services.state import State


def main(argv=None):
    parser = argparse.ArgumentParser(description="本机微信高清照片导出；默认仅预览。")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("accounts", help="列出本机账号目录")
    names = sub.add_parser("sessions", help="列出会话")
    names.add_argument("--account", required=True)
    names.add_argument("--refresh", action="store_true")
    job = sub.add_parser("export", help="预览或执行导出")
    job.add_argument("--account", required=True)
    job.add_argument("--output", required=True)
    job.add_argument("--apply", action="store_true", help="执行导出；省略时只预览")
    scope = job.add_mutually_exclusive_group(required=True)
    scope.add_argument("--all", action="store_true")
    scope.add_argument("--group", action="append")
    scope.add_argument("--session", action="append")
    args = parser.parse_args(argv)
    cancelled = threading.Event()
    previous = signal.signal(signal.SIGINT, lambda *_: cancelled.set())
    try:
        if args.command == "accounts":
            for account in discover_accounts():
                print(account.root)
            return 0
        account = account_at(args.account)
        with State(account) as state:
            if args.command == "sessions":
                if args.refresh:
                    refresh_names(account, state, cancelled.is_set, print)
                for row in sessions(account, state):
                    print(f"{row.name}\t{row.kind}\t{row.full_hash}")
                return 0
            choices = select_sessions([row.full_hash for row in sessions(account, state)], state.names(),
                                      args.group, args.session)
            plan = build_plan(account, state, choices, args.output, cancelled.is_set, print)
            print(f"预览：{len(plan.directories)} 个会话，{len(plan.items)} 张；源文件 {plan.source_bytes/1024**3:.2f} GB")
            if not args.apply or not plan.items:
                return 0
            from .platforms.windows import image_keys, decoder_path
            from .platforms.decoder import Decoder
            keys = image_keys(account, state, cancelled.is_set, print)
            decoder = Decoder(decoder_path())
            try:
                result = export(plan, state, keys, decoder, cancelled.is_set)
            finally:
                decoder.close()
            print(f"导出 {result.completed}，跳过 {result.skipped}，失败 {result.failed}，待转换 {result.pending_conversion}")
            for code, count in result.errors.items():
                print(f"{code}: {MESSAGES[code]} ({count})")
            return 130 if result.cancelled else (1 if result.failed or result.pending_conversion else 0)
    except ValueError as exc:
        # 群名错误用于本机交互，诊断报告中不收集此文本。
        print(str(exc))
        return 2
    except Exception as exc:
        code = error_code(exc)
        print(code+": "+MESSAGES[code])
        return 130 if code == "cancelled" else 1
    finally:
        signal.signal(signal.SIGINT, previous)
