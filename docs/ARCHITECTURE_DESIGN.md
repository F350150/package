# package-manager 详细设计文档（分支审计版）

## 1. 文档定位
本文档用于“设计审计”和“分支完整性审计”，目标是让评审者可以直接回答：
1. 编译期与运行期每个关键分支是否都被明确设计。
2. 每个分支的设计意图是否合理。
3. 每个分支是否有可执行的覆盖场景（UT/E2E）。

## 2. 总体设计意图
### 2.1 一致性目标
1. 所有产品遵循统一模板流程：解析 -> 下载 -> 验签 -> 安装 -> 清理 -> 状态更新。
2. 错误统一映射稳定退出码，避免非预期 traceback 泄漏。
3. 版本语义拆分明确，避免“项目目录版本”和“包文件版本”混淆。

### 2.2 可扩展性目标
1. 新产品优先通过 YAML 增量接入，不要求改核心流程。
2. 命名差异优先配置化（如 `rpm_arch_separator`），减少硬编码特判。
3. 特殊安装逻辑只放在产品子类，通用能力保留在中间父类。

### 2.3 鲁棒性目标
1. 下载具备重试、空间预判、原子替换。
2. 验签失败、下载失败、安装失败都应落在受控异常。
3. 回滚与清理不能覆盖主错误原因。

## 3. 关键数据契约
### 3.1 PackageConfig 语义
1. `product`：产品标识。
2. `version`：项目版本（project version）。
3. `artifact_version`：产物版本（包文件名使用）。
4. `package_format`：`rpm` 或 `tar.gz`。
5. `rpm_arch_separator`：rpm 文件名中版本与架构分隔符，支持 `-` 或 `.`。
6. `supported_versions`：允许的项目版本白名单。
7. `install_dir`：安装路径。
8. `enabled`：开关。

### 3.2 URL 组装契约
1. `download_defaults.base_url` 只包含固定前缀，不包含项目版本尾段。
2. 运行时 URL 组装规则：`base_url + project_version + filename`。
3. framework 包（devkit）与主包必须使用同一项目版本目录。

### 3.3 状态文件契约
1. 文件：`.package-manager/.install_state.yaml`。
2. 结构：`products.<product>.installed_version/...`。
3. `installed_version` 存的是项目版本，用于版本切换判断。

## 4. 架构与流程图索引
### 4.1 组件与总流程
1. [architecture_component.puml](/Users/fxl/pycharm_projects/package/docs/puml/architecture_component.puml)
2. [cli_to_install_sequence.puml](/Users/fxl/pycharm_projects/package/docs/puml/cli_to_install_sequence.puml)
3. [installer_template_activity.puml](/Users/fxl/pycharm_projects/package/docs/puml/installer_template_activity.puml)
4. [resolver_decision_activity.puml](/Users/fxl/pycharm_projects/package/docs/puml/resolver_decision_activity.puml)

### 4.2 编译期与子流程
1. [build_pipeline_activity.puml](/Users/fxl/pycharm_projects/package/docs/puml/build_pipeline_activity.puml)
2. [config_loader_activity.puml](/Users/fxl/pycharm_projects/package/docs/puml/config_loader_activity.puml)
3. [downloader_activity.puml](/Users/fxl/pycharm_projects/package/docs/puml/downloader_activity.puml)
4. [verifier_activity.puml](/Users/fxl/pycharm_projects/package/docs/puml/verifier_activity.puml)
5. [porting_advisor_installer_activity.puml](/Users/fxl/pycharm_projects/package/docs/puml/porting_advisor_installer_activity.puml)
6. [porting_cli_rpm_installer_activity.puml](/Users/fxl/pycharm_projects/package/docs/puml/porting_cli_rpm_installer_activity.puml)
7. [error_exitcode_state.puml](/Users/fxl/pycharm_projects/package/docs/puml/error_exitcode_state.puml)

## 5. 编译期设计（build.sh）
### 5.1 设计意图
1. 将运行依赖固化到 `dist/package-manager/_internal`，避免运行期依赖宿主环境差异。
2. 将根证书转为 PEM 并与内置 openssl 一起分发，保证验签链路可用。
3. 用 PyInstaller 生成独立可执行目录，屏蔽 Python 运行环境差异。

### 5.2 编译期分支清单
| 分支ID | 条件 | 设计意图 | 结果 |
|---|---|---|---|
| C-B01 | 构建参数缺失 | 防止未知默认版本 | 输出用法并退出 1 |
| C-B02 | `openssl` 不存在 | 验签依赖前置保障 | 退出 1 |
| C-B03 | `pyinstaller` 不存在 | 打包依赖前置保障 | 退出 1 |
| C-B04 | canonical DER 不存在但 fallback 存在 | 兼容旧文件名 | 自动复制 fallback |
| C-B05 | 两个 DER 都不存在 | 不允许无根证书产物 | 退出 1 |
| C-B06 | `PACKAGE_VERSION` 已相同 | 避免无意义写文件 | 跳过更新 |
| C-B07 | `PACKAGE_VERSION` 不同 | 对齐构建版本 | 修改 `config.py` 常量 |
| C-B08 | PyInstaller 失败 | 阻断坏产物 | 退出非0 |
| C-B09 | 复制 openssl 动态库存在/不存在 | 兼容不同平台 | 存在则拷贝，不存在则跳过 |
| C-B10 | 产物组装完成 | 运行期可执行保障 | 输出产物路径 |

### 5.3 编译期风险与约束
1. 当前动态库拷贝清单偏向 macOS 命名（`*.dylib`），Linux 上依赖系统动态链接解析。
2. 若需完全离线运行，可扩展 Linux `*.so` 复制策略并增加产物校验。

## 6. 运行期总流程设计
### 6.1 CLI 编排层意图
1. 入口参数保持极简，只暴露 name/id/list 三种用户模型。
2. 所有业务失败由 `InstallerError` 子类承载，映射固定退出码。

### 6.2 运行期全局分支
| 分支ID | 条件 | 设计意图 | 结果 |
|---|---|---|---|
| R-B01 | `--list-packages` | 只读检查，不触发副作用 | 列包并退出 0 |
| R-B02 | 同时传 `--name` 和 `--package-id` | 防止选择歧义 | `ConfigError(10)` |
| R-B03 | `--name` 无匹配启用项 | 快速反馈配置问题 | `ConfigError(10)` |
| R-B04 | `--package-id` 无匹配 | 避免误装 | `ConfigError(10)` |
| R-B05 | 全量安装模式 | 默认行为可预测 | 遍历 enabled packages |

## 7. 配置加载与校验设计（config.py）
### 7.1 设计意图
1. 配置错误尽早暴露，避免进入执行态后才失败。
2. 支持“打包态配置覆盖开发态配置”。
3. token 替换只做纯文本替换，不做表达式计算，降低复杂度。

### 7.2 分支清单
| 分支ID | 条件 | 结果 |
|---|---|---|
| CFG-B01 | 环境变量配置路径存在 | 使用环境变量路径 |
| CFG-B02 | 未配置环境变量且打包态配置存在 | 使用打包态路径 |
| CFG-B03 | 打包态配置不存在 | 回退项目目录路径 |
| CFG-B04 | 文件不存在 | `ConfigError(10)` |
| CFG-B05 | YAML 模块缺失 | `ConfigError(10)` |
| CFG-B06 | YAML 解析失败 | `ConfigError(10)` |
| CFG-B07 | 根节点不是 mapping | `ConfigError(10)` |
| CFG-B08 | `download_defaults` 结构错误 | `ConfigError(10)` |
| CFG-B09 | `verify_defaults` 结构错误 | `ConfigError(10)` |
| CFG-B10 | `packages` 不是 list | `ConfigError(10)` |
| CFG-B11 | `packages[i]` 不是 mapping | `ConfigError(10)` |
| CFG-B12 | 必填字段缺失或空 | `ConfigError(10)` |
| CFG-B13 | `supported_versions` 非 list | `ConfigError(10)` |
| CFG-B14 | `project_version` 不在 `supported_versions` | `ConfigError(10)` |
| CFG-B15 | `rpm_arch_separator` 非 `-/.` | `ConfigError(10)` |

## 8. 解析层设计（resolver.py）
### 8.1 设计意图
1. 单一入口解析，输出 `ResolvedPackage`，避免分散拼接逻辑。
2. URL 和文件名分离建模，支撑项目版本与产物版本独立演进。
3. 优先配置化处理命名差异。

### 8.2 分支清单
| 分支ID | 条件 | 结果 |
|---|---|---|
| RES-B01 | `uname -m` 成功且可识别 | 归一化为 `arm64/x86_64` |
| RES-B02 | `uname -m` 失败 | 回退 `platform.machine()` |
| RES-B03 | 架构不支持 | `ConfigError(10)` |
| RES-B04 | 包格式不支持 | `ConfigError(10)` |
| RES-B05 | `filename_override` 存在 | 直接使用 override |
| RES-B06 | tar.gz 文件名 | `product-token + artifact_version + arch_token` |
| RES-B07 | rpm 文件名 | 使用 `rpm_arch_separator` 拼接 |
| RES-B08 | `base_url` 已含 `project_version` | 不重复拼接 |
| RES-B09 | `base_url` 以 `%20` 或 `/` 结尾 | 直接拼接 project_version |
| RES-B10 | 普通路径前缀 | 用 `/` 拼接 project_version |

## 9. 下载层设计（downloader.py）
### 9.1 设计意图
1. 提前发现空间问题，避免下载到中途失败。
2. 通过 `.tmp` + 原子替换保证目标文件一致性。
3. HEAD 探测与本地尺寸比较减少重复下载。

### 9.2 分支清单
| 分支ID | 条件 | 结果 |
|---|---|---|
| DL-B01 | `TLS_INSECURE=1` | 使用不校验证书上下文并告警 |
| DL-B02 | 默认 TLS | 加载系统 CA + 内置 root_ca（若存在） |
| DL-B03 | 额外 `TLS_CA_FILE_ENV` | 加载额外 CA |
| DL-B04 | HEAD 失败 | `remote_size=None`，继续下载 |
| DL-B05 | 本地文件可复用 | skip 下载 |
| DL-B06 | 远端大小未知且空间不足 | `DownloadError(20)` |
| DL-B07 | 远端大小已知且空间不足 | `DownloadError(20)` |
| DL-B08 | 下载后空间偏低 | warning，不中断 |
| DL-B09 | retry 次数小于1 | 归一化为1次 |
| DL-B10 | 单次下载异常 | 记录并重试 |
| DL-B11 | 所有重试失败 | `DownloadError(20)` |
| DL-B12 | 下载结果为空文件 | `DownloadError(20)` |
| DL-B13 | 下载成功 | tmp 原子替换为目标文件 |

## 10. 验签层设计（verifier.py）
### 10.1 设计意图
1. 默认要求证书链校验，提供可控降级开关。
2. 运行时优先内置 openssl，兼容系统 openssl 回退。

### 10.2 分支清单
| 分支ID | 条件 | 结果 |
|---|---|---|
| VF-B01 | `signature_format` 非 DER/PEM | `SignatureVerifyError(40)` |
| VF-B02 | `verify_chain=true` 且 root_ca 缺失 | `SignatureVerifyError(40)` |
| VF-B03 | `verify_chain=false` | 使用 `-noverify` 并告警 |
| VF-B04 | 内置 openssl 存在 | 使用内置 openssl |
| VF-B05 | 内置 openssl 不存在 | 回退系统 openssl |
| VF-B06 | openssl returncode=0 | 验签成功 |
| VF-B07 | openssl returncode!=0 | `SignatureVerifyError(40)` |

## 11. 安装模板设计（BaseInstaller）
### 11.1 设计意图
1. 用模板方法锁定主流程顺序，防止产品子类绕过关键步骤。
2. 把产品差异限制在 `pre_check/remove_previous/install/rollback`。
3. 任何失败路径都尝试“安全回滚 + 安全清理”。

### 11.2 模板分支清单
| 分支ID | 条件 | 结果 |
|---|---|---|
| INS-B01 | 已安装版本存在且不等于目标项目版本 | 调用 `remove_previous_version` |
| INS-B02 | `pre_check.should_install=false` | skip + `record_install_success` |
| INS-B03 | 主流程全部成功 | `record_install_success` + completed |
| INS-B04 | 抛出 InstallerError | rollback_safely + cleanup_temp_safely + 原样抛出 |
| INS-B05 | 抛出未知异常 | rollback_safely + cleanup_temp_safely + 转 `InstallError(50)` |
| INS-B06 | cleanup_temp 失败 | `CleanupError(60)`（主流程成功时） |
| INS-B07 | rollback/cleanup safe 失败 | 仅记录日志，不覆盖主异常 |

## 12. 产品安装器设计
### 12.1 TarGzInstaller 通用分支
| 分支ID | 条件 | 结果 |
|---|---|---|
| TG-B01 | 同版本且 install_dir 存在 | skip |
| TG-B02 | 版本切换 | 删除 install_dir |
| TG-B03 | 存在 install.sh | 执行脚本，失败则 `InstallError(50)` |
| TG-B04 | install_dir 最终不存在 | `InstallError(50)` |

### 12.2 RpmInstaller 通用分支
| 分支ID | 条件 | 结果 |
|---|---|---|
| RPM-B01 | 同版本 | skip |
| RPM-B02 | 版本切换卸载失败 | 忽略并继续 |
| RPM-B03 | `rpm` 命令缺失 | `InstallError(50)` |
| RPM-B04 | `rpm -Uvh` 失败 | `InstallError(50)` |
| RPM-B05 | `rpm -q` 失败 | `InstallError(50)` |

### 12.3 Porting-Advisor 特化分支
| 分支ID | 条件 | 结果 |
|---|---|---|
| PA-B01 | 同版本且 `config/jre/jar` 结构完整 | skip |
| PA-B02 | payload 在 base_dir | 直接使用 |
| PA-B03 | payload 在子目录 | 搜索命中后使用 |
| PA-B04 | payload 未找到 | `InstallError(50)` |
| PA-B05 | 缺少 `Sql-Analysis*.tar.gz` 或 `jre*.tar.gz` | `InstallError(50)` |
| PA-B06 | 缺少 `config` 或 `jre` 或 `jar` | `InstallError(50)` |
| PA-B07 | 安装后布局校验失败 | `InstallError(50)` |

### 12.4 devkit-porting 特化分支
| 分支ID | 条件 | 结果 |
|---|---|---|
| PC-B01 | 同版本且 `DevKit-Porting-CLI/devkit` 存在 | skip |
| PC-B02 | 版本切换 | 卸载旧 rpm + 删除旧目录 |
| PC-B03 | framework URL 拼接 | 必须与主包使用同一项目版本目录 |
| PC-B04 | 主包或 framework 下载失败 | `DownloadError(20)` |
| PC-B05 | 主包或 framework 验签失败 | `SignatureVerifyError(40)` |
| PC-B06 | 双 rpm 任意安装失败 | `InstallError(50)` |
| PC-B07 | porting_root 创建失败 | `InstallError(50)` |
| PC-B08 | 旧 target 清理失败 | `InstallError(50)` |
| PC-B09 | relocate 结果 `_internal/devkit` 缺失 | `InstallError(50)` |
| PC-B10 | rename 失败 | `InstallError(50)` |

## 13. 状态持久化设计（install_state.py）
### 13.1 设计意图
1. 把“是否已安装、安装到哪个项目版本”从安装目录探测中解耦。
2. 状态写入采用原子替换，避免中断损坏。

### 13.2 分支清单
| 分支ID | 条件 | 结果 |
|---|---|---|
| ST-B01 | 状态文件不存在 | 返回空结构 |
| ST-B02 | 状态 YAML 损坏 | `ConfigError(10)` |
| ST-B03 | 状态根结构非预期 | 回退空结构 |
| ST-B04 | 产品节点不存在 | `installed_version=None` |
| ST-B05 | 更新状态 | 原子写入 `.tmp -> replace` |

## 14. 退出码设计意图
1. `10`：配置/输入错误，通常用户可修复。
2. `20`：下载链路错误，通常网络/源端问题。
3. `40`：验签错误，属于安全风险。
4. `50`：安装执行错误，通常系统状态或包内容问题。
5. `60`：清理失败（主流程成功后）。
6. `1`：未知异常兜底，代表设计外分支。

## 15. 分支覆盖矩阵（设计到测试）
### 15.1 覆盖映射说明
1. UT 文件与 E2E 场景定义详见 [TESTING_GUIDE.md](/Users/fxl/pycharm_projects/package/docs/TESTING_GUIDE.md)。
2. 本表用于判断“每个设计分支是否已有验证入口”。

| 设计分支组 | 主要分支ID | 覆盖方式 |
|---|---|---|
| 编译期工具与证书前置 | C-B01..C-B05 | Build 脚本执行验证（E2E 前置） |
| 配置解析与约束 | CFG-B01..CFG-B15 | `test_config_runtime.py` + `S05/S12` |
| 解析规则与双版本 | RES-B01..RES-B10 | `test_resolver.py` + `test_porting_cli_urls.py` + `S03` |
| 下载重试与空间/TLS分支 | DL-B01..DL-B13 | `test_downloader.py` + `S13` |
| 验签链路与格式分支 | VF-B01..VF-B07 | `test_p7s_verifier.py` + `S14/S19` |
| 模板主流程与异常封装 | INS-B01..INS-B07 | `test_installer_flow.py` + `S20` |
| tar/rpm 通用分支 | TG-B01..TG-B04, RPM-B01..RPM-B05 | `test_installer_flow.py` + `S01..S04/S16` |
| Porting-Advisor 特化分支 | PA-B01..PA-B07 | `test_porting_advisor_layout.py` + `S01/S02/S08` |
| devkit-porting 特化分支 | PC-B01..PC-B10 | `test_porting_cli_urls.py` + `S03/S04/S18` |
| 状态持久化 | ST-B01..ST-B05 | `test_install_state.py` + `S11` |
| 入口参数冲突与选择 | R-B01..R-B05 | `test_installer_service.py` + `S10` |

## 16. 已知边界与后续建议
1. `S17`（破坏 Porting-Advisor 压缩包完整性）当前策略上由验签保障，不纳入默认 E2E。
2. 若将来支持更多 rpm 命名风格，建议新增 `filename_pattern` 模板字段，替代更多特化代码。
3. 编译期建议补充 Linux 动态库复制策略与产物自检脚本，进一步降低环境耦合。
4. 当前回滚策略以“幂等清理”为主，若未来需要可审计恢复点，可引入事务日志。

## 17. 审计使用方法（给评审者）
1. 先看图：组件图 -> 编译期图 -> 运行期时序图。
2. 再看分支：按章节 5~13 的分支表逐条核对。
3. 最后看覆盖：章节 15 确认每组分支是否有 UT/E2E 入口。
4. 如发现某分支无覆盖，可在 `TESTING_GUIDE` 中追加场景 ID 并回填矩阵。
