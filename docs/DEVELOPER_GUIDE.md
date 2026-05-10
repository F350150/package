# 开发者文档

## 1. 先读什么
1. `src/package_manager/main.py`：了解 CLI 到服务层调用入口。
2. `src/package_manager/service.py`：看整体业务编排。
3. `src/package_manager/installers.py`：看模板方法与安装器分层。
4. `src/package_manager/resolver.py`：看架构识别、文件名和包元信息推导。
5. `src/package_manager/downloader.py`：看下载可靠性与性能策略。
6. `src/package_manager/verifier.py`：看 OpenSSL 验签策略。

## 2. 运行流程（简版）
1. `main` 解析参数并调用 `run_with_builtin_config`（仅支持 `--name`）。
2. `service` 选择目标配置并转为 `ResolvedPackage`。
3. 安装器执行：本地命中检查 -> 下载兜底 -> 验签 -> 安装 -> 清理。
4. 异常统一映射为稳定退出码。

## 3. 版本语义（必须遵守）
1. `project_version`（运行时映射到 `PackageConfig.version`）：项目版本（用于下载目录和安装状态比较）。
2. `artifact_version`：产物版本（用于文件名）。
3. `rpm_arch_separator`：rpm 包版本和架构的分隔符（`-` 或 `.`）。
4. 任何新增产品都要明确这三个字段语义，不能混用。

## 4. 如何新增一个产品
1. 在 `packages.yaml` 增加配置：`product/project_version/artifact_version/package_format/install_dir`。
2. 如 rpm 命名是 `x.y.z.aarch64.rpm` 这种形式，配置 `rpm_arch_separator: "."`。
2. 在 `installers.py` 新增产品子类：
   - `class XxxTarGzInstaller(TarGzInstaller)`
   - `class XxxRpmInstaller(RpmInstaller)`（如需要）
3. 在 `INSTALLER_REGISTRY` 注册：`("xxx", "tar.gz") -> XxxTarGzInstaller`。
4. 补充 UT + E2E 场景，至少覆盖 pre_check 通过/跳过、下载失败、验签失败。

## 5. 如何新增一种包格式
1. 在 `models.py` 和 `resolver.py` 扩展合法格式。
2. 在 `resolver.arch_token_for_package` 增加映射规则。
3. 在 `installers.py` 增加新的中间安装器。
4. 在注册表映射到对应产品。

## 6. 离线安装策略（新特性）
1. 外部接口不变，不新增 CLI 参数。
2. 内部逻辑统一走 `ensure_local_or_download`：
   - 本地目标文件存在且非空：直接使用；
   - 本地缺失或空文件：尝试下载；
   - 下载失败：抛出带“离线投放路径提示”的错误。
3. `devkit-porting` 要同时覆盖四个文件：主包、主签名、framework 包、framework 签名。

## 7. 性能与可靠性设计
- 下载前先 `HEAD` 探测大小。
- 下载前校验磁盘空间。
- 下载后剩余空间过低会 warning。
- 流式大块拷贝（8MB）减少系统调用开销。
- 本地已有同尺寸文件时可跳过重复下载。

## 8. 约束与风格
- 函数尽量短小（<=50 行），每个函数只做一件事。
- 圈复杂度控制在 <=4，必要时拆 helper。
- 关键模块和函数写中文注释，优先解释“为什么”。
- 路径处理统一走 `paths.py`，不要散落硬编码。

## 9. 安装路径策略
- 每个包可在 `PackageConfig.install_dir` 指定安装目录。
- 支持绝对路径和相对路径：
  - 绝对路径：直接使用。
  - 相对路径：相对 `app_dir`（即二进制同级目录）解析。
- `install_dir` 为必填；缺失会在配置加载阶段直接报错。
