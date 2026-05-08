# 开发者文档

## 1. 先读什么
1. `src/package_manager/main.py`：了解 CLI 到服务层调用入口。
2. `src/package_manager/service.py`：看整体业务编排。
3. `src/package_manager/installers.py`：看模板方法与安装器分层。
4. `src/package_manager/resolver.py`：看架构识别、文件名和 package-id 推导。
5. `src/package_manager/downloader.py`：看下载可靠性与性能策略。
6. `src/package_manager/verifier.py`：看 OpenSSL 验签策略。

## 2. 运行流程（简版）
1. `main` 解析参数并调用 `run_with_builtin_config`。
2. `service` 选择目标配置并转为 `ResolvedPackage`。
3. 安装器执行：下载 -> 验签 -> 安装 -> 清理。
4. 异常统一映射为稳定退出码。

## 3. 如何新增一个产品
1. 在 `config.py` 增加 `PackageConfig(product=..., version=..., package_format=..., install_dir=...)`。
2. 在 `installers.py` 新增产品子类：
   - `class XxxTarGzInstaller(TarGzInstaller)`
   - `class XxxRpmInstaller(RpmInstaller)`（如需要）
3. 在 `INSTALLER_REGISTRY` 注册：`("xxx", "tar.gz") -> XxxTarGzInstaller`。
4. 补充单元测试。

## 4. 如何新增一种包格式
1. 在 `models.py` 和 `resolver.py` 扩展合法格式。
2. 在 `resolver.arch_token_for_package` 增加映射规则。
3. 在 `installers.py` 增加新的中间安装器。
4. 在注册表映射到对应产品。

## 5. 性能与可靠性设计
- 下载前先 `HEAD` 探测大小。
- 下载前校验磁盘空间。
- 下载后剩余空间过低会 warning。
- 流式大块拷贝（8MB）减少系统调用开销。
- 本地已有同尺寸文件时可跳过重复下载。

## 6. 约束与风格
- 函数尽量短小（<=50 行），每个函数只做一件事。
- 圈复杂度控制在 <=4，必要时拆 helper。
- 关键模块和函数写中文注释，优先解释“为什么”。
- 路径处理统一走 `paths.py`，不要散落硬编码。

## 7. 安装路径策略
- 每个包可在 `PackageConfig.install_dir` 指定安装目录。
- 支持绝对路径和相对路径：
  - 绝对路径：直接使用。
  - 相对路径：相对 `app_dir`（即二进制同级目录）解析。
- 若未配置 `install_dir`，默认回退到 `_internal/products/<product>`。
