"""构建期 YAML 渲染工具。

职责：
1. 读取 `packages.template.yaml`
2. 将 `${PACKAGE_VERSION}` 替换为构建版本
3. 输出运行时 `packages.yaml`
"""

import argparse
from pathlib import Path
from typing import Any

import yaml

PACKAGE_VERSION_TOKEN = "${PACKAGE_VERSION}"


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(description="Render packages.template.yaml for build output")
    parser.add_argument("--template", required=True, help="模板 YAML 路径")
    parser.add_argument("--output", required=True, help="输出 YAML 路径")
    parser.add_argument("--version", required=True, help="构建版本号")
    return parser.parse_args()


def substitute_tokens(value: Any, version: str) -> Any:
    """递归替换 YAML 结构中的版本占位符。"""

    if isinstance(value, str):
        return value.replace(PACKAGE_VERSION_TOKEN, version)
    if isinstance(value, list):
        return [substitute_tokens(item, version) for item in value]
    if isinstance(value, dict):
        return {k: substitute_tokens(v, version) for k, v in value.items()}
    return value


def render_template(template_path: Path, output_path: Path, version: str) -> None:
    """执行模板渲染。"""

    raw = yaml.safe_load(template_path.read_text(encoding="utf-8")) or {}
    rendered = substitute_tokens(raw, version)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(rendered, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"Generated runtime YAML: {output_path}")


def main() -> int:
    """构建渲染入口。"""

    args = parse_args()
    render_template(Path(args.template), Path(args.output), args.version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

