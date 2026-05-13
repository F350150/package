# package-manager 测试文档（UT + E2E）

## 1. 目标与范围
本测试文档用于保证三件事：
1. 版本语义拆分（`project version` 与 `artifact version`）不回退。
2. 安装主流程和异常分支行为稳定，退出码可预测。
3. 容器中的真实下载/验签/安装链路可重复回归。

覆盖范围：
1. 单元测试（UT）：函数级与模块级行为验证。
2. 端到端测试（E2E）：构建产物后在容器执行真实流程。

## 2. 测试分层策略
### 2.1 UT 层（快速、细粒度）
关注点：
1. 解析规则。
2. 配置校验。
3. 安装流程模板分支。
4. 下载与验签边界行为。
5. 状态文件读写稳定性。

### 2.2 E2E 层（真实链路）
关注点：
1. 构建产物是否可运行。
2. 两个关键安装器在真实资源上的表现。
3. 异常场景退出码、日志关键字、文件系统副作用是否符合设计。

## 3. UT 用例设计
### 3.1 配置与模型
1. `tests/test_config_runtime.py`
   - YAML 语法错误 -> `ConfigError`。
   - 缺失必填字段 -> `ConfigError`。
   - 项目版本不在 `supported_versions` -> `ConfigError`。
   - `rpm_arch_separator` 非法值 -> `ConfigError`。

2. `tests/test_install_state.py`
   - 状态 YAML 损坏 -> `ConfigError`。
   - 状态更新后可读回版本。
3. `tests/test_file_lock.py`
   - 死进程锁自动回收。
   - TTL 过期锁自动回收。
   - 活锁超时保护，不误删持锁文件。

### 3.2 解析层
1. `tests/test_resolver.py`
   - URL 使用 `project version`。
   - 文件名使用 `artifact_version`。
   - rpm `-` 分隔符规则。
   - rpm `.` 分隔符规则（devkit 场景）。
   - product 直接参与文件名拼接（无产品 token 特判）。

2. `tests/test_porting_cli_urls.py`
   - devkit framework 包 URL 必须拼接项目版本目录。

### 3.3 安装流程层
1. `tests/test_installer_flow.py`
   - 成功路径。
   - 下载失败触发回滚与清理。
   - 验签失败不进入安装。
   - 安装失败触发回滚。
   - 版本切换触发 remove_previous。
   - pre_check skip 分支。

2. `tests/test_porting_advisor_layout.py`
   - DevKit-Porting-Advisor payload 目录识别。
   - 运行时成品（config/jre/jar）发布流程。

### 3.4 服务与入口层
1. `tests/test_installer_service.py`
   - 仅按 name 选择；缺失 name 或参数不支持时失败。
   - 空 name 输入校验。

2. `tests/test_main.py`
   - main 到 service 的参数透传。
   - `ConfigError` 映射稳定退出码。

### 3.5 下载与验签
1. `tests/test_downloader.py`
   - 下载成功、失败、空文件、空间不足、TLS 配置分支。
   - 断点续传（Range）与降级全量下载分支。
2. `tests/test_p7s_verifier.py`
   - 验签成功、验签失败。
   - verify_chain 真假分支。
   - 根证书缺失分支。

## 4. E2E 用例设计
执行脚本：`scripts/e2e_cases.sh`

### 4.1 场景清单（默认执行）
1. `S01` DevKit-Porting-Advisor 首次安装（pre_check 通过）。
2. `S02` DevKit-Porting-Advisor 重复安装（pre_check skip）。
3. `S03` devkit-porting 首次安装。
4. `S04` devkit-porting 重复安装（skip）。
5. `S05` 项目版本不在 `supported_versions`。
6. `S06` 旧版本 -> 目标版本（触发切换）。
7. `S07` 高版本 -> 目标版本（触发切换）。
8. `S08` DevKit-Porting-Advisor 成品目录必须包含 `config/jre/sql-analysis-*.jar`。
9. `S09` 成功后下载缓存目录被清理。
10. `S10` 传入不支持的 `--package-id` 参数（argparse 拒绝）。
11. `S11` install_state YAML 损坏。
12. `S12` config YAML 损坏。
13. `S13` 下载 URL 不可达。
14. `S14` 验签失败（通过错误 signature_format 注入）。
15. `S15` 架构不支持（伪造 `uname -m`）。
16. `S16` 同版本记录但安装目录缺失，必须重装而不是 skip。
17. `S18` devkit-porting 目录整理失败分支。
18. `S19` 根证书缺失分支。
19. `S20` 清理失败分支（主错误不被清理错误覆盖）。
20. `S21` DevKit-Porting-Advisor 本地包+签名命中，网络不可达仍可安装。
21. `S22` DevKit-Porting-Advisor 主包命中，签名缺失可在线补齐。
22. `S23` DevKit-Porting-Advisor 主包为空文件且网络不可达，提示离线投放路径。
23. `S24` DevKit-Porting-Advisor 主包缺失且网络不可达，提示离线投放路径。
24. `S25` devkit-porting（主包/签名/framework/签名）四文件都本地命中，网络不可达仍可安装。
25. `S26` devkit-porting framework 主包缺失，网络可达可补齐安装。
26. `S27` devkit-porting framework 主包缺失且网络不可达，提示离线投放路径。
27. `S28` devkit-porting framework 主包为空文件且网络不可达，提示离线投放路径。
28. `S29` devkit-porting framework 签名缺失且网络不可达，提示离线投放路径。
29. `S30` 并发状态写入锁：多进程并发更新 install_state 不丢记录。
30. `S31` 断点续传：预置 `.tmp` 后走 HTTP Range 续传并安装成功。
31. `S32` 缓存策略 `keep_latest`：保留缓存并在离线重装时复用本地包。
32. `S33` 陈旧锁清理：预置 stale `.lock` 后安装成功并更新状态。
33. `S34` 活锁保护：持锁进程存活时竞争方超时且锁不被误删。

说明：`S17` 当前按产品策略显式跳过。

### 4.2 断言维度
每个场景至少命中三类断言：
1. 退出码断言。
2. 日志关键字断言。
3. 文件系统副作用断言（目录存在/缺失）。

## 5. 分支-场景映射矩阵
| 分支类别 | 分支点 | UT 覆盖 | E2E 覆盖 |
|---|---|---|---|
| 入口分支 | name 必填/不支持参数 | `test_installer_service.py` | `S10` |
| 配置分支 | YAML 错误/字段缺失/版本约束/rpm 分隔符约束 | `test_config_runtime.py` | `S05`,`S12` |
| 解析分支 | project/artifact 双版本、rpm 分隔符、product 直拼 | `test_resolver.py`,`test_porting_cli_urls.py` | `S03` |
| pre_check 分支 | should_install / skip | `test_installer_flow.py` | `S01`,`S02`,`S03`,`S04`,`S16` |
| 版本切换分支 | installed != target | `test_installer_flow.py` | `S06`,`S07` |
| 下载分支 | 成功/失败/重试 | `test_downloader.py` | `S01`,`S03`,`S13` |
| 离线优先分支 | 本地命中/缺失下载/缺失且不可下载/空文件 | `test_installer_flow.py` | `S21`~`S29` |
| 下载续传分支 | `.tmp` 续传/Range 命中/降级全量 | `test_downloader.py` | `S31` |
| 缓存策略分支 | `keep_latest` 保留最新缓存 | `test_installer_flow.py` | `S32` |
| 文件锁分支 | 陈旧锁回收/活锁保护 | `test_file_lock.py` | `S30`,`S33`,`S34` |
| 验签分支 | 成功/失败 | `test_p7s_verifier.py` | `S14` |
| 配置/证书分支 | 内置根证书缺失 | `test_paths.py` | `S19` |
| 安装异常分支 | 安装失败/目录整理失败 | `test_installer_flow.py` | `S18` |
| 清理分支 | cleanup 成功/失败 | `test_installer_flow.py` | `S09`,`S20` |
| 状态文件分支 | 读坏/写回/读回 | `test_install_state.py` | `S11` |

## 6. 如何执行
### 6.1 执行 UT
```bash
cd /Users/fxl/pycharm_projects/package
pytest -q
```

### 6.2 执行 E2E（推荐容器）
```bash
cd /Users/fxl/pycharm_projects/package
./scripts/e2e_cases.sh --container openeuler-arm
```

### 6.3 仅本机执行 E2E
```bash
cd /Users/fxl/pycharm_projects/package
./scripts/e2e_cases.sh
```

## 7. E2E 前置条件
1. 可访问目标下载源。
2. 容器存在且可执行 `docker exec`。
3. 容器内可安装或已具备 `pyinstaller`、`pyyaml`。
4. 脚本可读写 `dist/` 与 `e2e_logs/`。

## 8. E2E 结果判定标准
满足以下全部条件判定通过：
1. summary 中 `failed=0`。
2. 所有场景退出码与预期一致。
3. S08/S09 文件系统断言通过。
4. 关键异常场景（S13/S14/S18/S19/S20/S23/S24/S27/S28/S29/S34）日志包含预期关键字。
5. 离线提示场景日志必须包含 `Offline install hint` 和目标投放路径。
6. 续传场景需出现 `resume_from` 且命中 `range_status=206`。
7. 锁场景需验证：S33 陈旧锁被清理，S34 活锁不被误删。

## 9. 回归建议
1. 每次改动 `resolver/config/installer` 任一模块时至少跑 UT。
2. 版本语义、下载 URL、安装器流程有改动时必须跑 E2E。
3. 发布前保留最近一次 E2E `summary.txt` 与日志目录以便审计。
