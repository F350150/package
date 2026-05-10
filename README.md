# package-manager

YAML 配置、自动下载、P7S 验签、通过后安装的工具包管理器。

## 核心特点
- 配置外置到 YAML（`config/packages.yaml`），支持独立更新版本与下载地址
- 版本语义拆分：`project_version`（项目版本）与 `artifact_version`（包自身版本）
- 运行时自动识别架构并推导包名
- 离线优先安装：本地包命中直接安装，缺失时自动下载，下载失败给出离线投放路径提示
- 下载前远端大小探测 + 磁盘空间预检查
- `.tmp` 原子下载与重试
- `openssl cms -verify` 做 detached `.p7s` 验签
- 安装器分层：`BaseInstaller -> TarGzInstaller/RpmInstaller -> 产品子类`
- 安装状态落盘到隐藏文件 `.package-manager/.install_state.yaml`
- `_internal` 目录分离打包依赖
- 安装路径可在配置中按产品独立指定（`install_dir`）

## 项目结构
- `config/packages.yaml`：外置配置（下载参数、包定义、支持版本）
- `src/package_manager/config.py`：YAML 配置加载器
- `src/package_manager/install_state.py`：隐藏状态文件读写
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
python -m package_manager.main --name DevKit-Porting-Advisor
python -m package_manager.main --name devkit-porting
```

## 一键构建
```bash
./scripts/build.sh 26.0.RC1
```

## 一键构建并运行（Quick Start）
```bash
./scripts/quick_start.sh
```

在已有容器中执行完整测试流程：
```bash
./scripts/quick_start.sh --container openeuler-arm --test-porting-installers
```

执行完整端到端场景（S01-S16、S18-S29，默认跳过 S17）：
```bash
./scripts/e2e_cases.sh --container openeuler-arm
```

说明：
- `quick_start.sh` 不会使用 `sudo`。
- 安装路径由 `config/packages.yaml` 中每个包的 `install_dir` 控制。
- 容器模式会把当前项目复制到容器临时目录后执行同一脚本；默认自动安装 `pytest`、`pyinstaller`、`pyyaml`（可用 `--container-no-bootstrap` 关闭）。
- `e2e_cases.sh` 会输出场景级返回码与日志目录，便于回归对比与问题定位。
- `e2e_cases.sh` 已包含离线安装新特性分支场景（本地命中、缺失补齐、不可下载提示、空文件分支、framework 分支）。

构建脚本会自动：
- 用 `config/packages.template.yaml` 渲染构建产物配置 `dist/package-manager/config/packages.yaml`
- 从 `pems/huawei_integrity_root_ca_g2.der` 生成 PEM
- 复制 `openssl` 到 `_internal/openssl/bin/openssl`
- 复制 PEM 到 `_internal/openssl/pems/`
- 生成 `dist/package-manager/package-manager`
- 将依赖同步到产物目录的 `_internal`

## 开发者文档
详见：[开发者文档](/Users/fxl/pycharm_projects/package/docs/DEVELOPER_GUIDE.md)

详细设计文档（含 PUML 图）：
- [架构详细设计](/Users/fxl/pycharm_projects/package/docs/ARCHITECTURE_DESIGN.md)

测试文档（UT/E2E 用例设计与执行）：
- [测试指南](/Users/fxl/pycharm_projects/package/docs/TESTING_GUIDE.md)
