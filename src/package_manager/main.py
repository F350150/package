"""命令行入口。"""

import argparse
import sys
from typing import List, Optional

from package_manager.errors import InstallerError


def parse_args(argv: List[str]) -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(description="Package installer with built-in config and P7S verification")
    parser.add_argument("--name", help="按产品名安装所有启用配置")
    parser.add_argument("--package-id", help="仅安装指定 package-id")
    parser.add_argument("--verbose", action="store_true", help="预留参数，当前仅保持兼容")
    parser.add_argument("--list-packages", action="store_true", help="列出内置包")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """程序主入口。"""

    args = parse_args(normalize_argv(argv))
    try:
        # 延迟导入，确保配置加载异常能被统一错误处理捕获。
        from package_manager.service import run_with_builtin_config

        return run_with_builtin_config(name=args.name, package_id=args.package_id, list_packages=args.list_packages)
    except InstallerError as exc:
        print(f"Installer error: {exc}")
        return exc.exit_code
    except Exception:
        print("Unexpected error")
        return 1


def normalize_argv(argv: Optional[List[str]]) -> List[str]:
    """规范化 argv。"""

    return argv if argv is not None else sys.argv[1:]


if __name__ == "__main__":
    raise SystemExit(main())
