# package-manager

内置配置、自动下载、P7S 验签、通过后安装的工具包管理器。

## 核心特点
- 无 JSON/YAML 外部配置（全部内置 Python 配置）
- 运行时自动识别架构并推导包名
- 下载前远端大小探测 + 磁盘空间预检查
- `.tmp` 原子下载与重试
- `openssl cms -verify` 做 detached `.p7s` 验签
- 安装器分层：`BaseInstaller -> TarGzInstaller/RpmInstaller -> 产品子类`
- `_internal` 目录分离打包依赖
- 安装路径可在配置中按产品独立指定（`install_dir`）

## 项目结构
- `src/package_manager/config.py`：内置配置
- `src/package_manager/models.py`：数据模型
- `src/package_manager/errors.py`：错误与退出码
- `src/package_manager/paths.py`：路径管理
- `src/package_manager/resolver.py`：配置解析与文件名推导
- `src/package_manager/downloader.py`：下载与空间校验
- `src/package_manager/verifier.py`：OpenSSL 验签
- `src/package_manager/installers.py`：安装器层与注册表
- `src/package_manager/service.py`：业务编排入口
- `src/package_manager/main.py`：CLI 入口

## CLI
```bash
python -m package_manager.main --list-packages
python -m package_manager.main --name tiancheng
python -m package_manager.main --package-id <package-id-from-list>
```

## 一键构建
```bash
./scripts/build.sh 26.0.RC1
```

## 一键构建并运行（Quick Start）
```bash
./scripts/quick_start.sh
```

仅构建并列包（不安装）：
```bash
./scripts/quick_start.sh --list-only
```

指定 package-id 安装：
```bash
./scripts/quick_start.sh --package-id <package-id-from-list>
```

说明：
- `quick_start.sh` 不会使用 `sudo`。
- 安装路径由 `src/package_manager/config.py` 中每个 `PackageConfig.install_dir` 控制。

构建脚本会自动：
- 更新 `config.py` 的 `PACKAGE_VERSION`
- 从 `pems/huawei_integrity_root_ca_g2.der` 生成 PEM
- 复制 `openssl` 到 `_internal/openssl/bin/openssl`
- 复制 PEM 到 `_internal/openssl/pems/`
- 生成 `dist/package-manager/package-manager`
- 将依赖同步到产物目录的 `_internal`

## 开发者文档
详见：[开发者文档](/Users/fxl/pycharm_projects/package/docs/DEVELOPER_GUIDE.md)
