# Simple-CI 机密日志与产物保护（2026-10-30）

此仓库是公开 CI 启动器，私有源码检出、Unity 编译、签名与 iOS 上传逻辑由 age 加密的实现驱动。

## Android 产物

Android 的 APK、AAB、诊断日志分别打包：**APK/AAB 使用 `ci/artifact-recipient.txt`，日志单独使用临时 `ci/log-recipient.txt` 公钥**。构建成功后预期出现：

- `android-apk-sealed-<run_id>`：`android-apk-<run_id>.tar.gz.age`
- `android-aab-sealed-<run_id>`：`android-aab-<run_id>.tar.gz.age`
- `android-logs-sealed-<run_id>`：`android-logs-<run_id>.tar.gz.age`

若构建失败，不应上传不完整的 APK/AAB；日志只做 best-effort 加密收集。脚本对 APK/AAB 做 ZIP 及 Manifest 结构检查，但**完整资源、签名、可运行性必须由加密构建逻辑和实体机验证**。

## iOS 产物

iOS 现已拆分为 `ios-logs-sealed-<run_id>`（`ios-logs-<run_id>.tar.gz.age`，日志临时公钥）以及 `ios-sealed-<run_id>`（`ios-<run_id>.tar.age`，原有产物公钥，仅包含已有的 `build-outputs/`）。即使构建失败也尝试封存日志；如果没有 `dist` 目录则不上传输出包。成功签名及上传 TestFlight 的行为仍由私有脚本负责。iOS 构建已通过 `safe-progress.py --platform ios` 接入安全心跳、Watchdog 和独立加密健康记录 `health-ios.jsonl`。

## 日志保护边界

- Unity / Xcode 的原始 stdout、stderr 仅进入 Runner 的私有临时目录，不直接发到公开 Actions 控制台。
- Android 监控公开固定的阶段、心跳与失败类别，不公开文件名、源码、许可证及构建原始日志。
- `ci/recipient.txt` 用于**解密 CI 实现**，`ci/artifact-recipient.txt` 用于**APK/AAB/iOS 构建产物**，`ci/log-recipient.txt` 仅用于**Android/iOS 私有诊断日志**。三把 age 公钥相互独立。日志临时私钥**绝不**提交公开仓库、写入工作流或存为 GitHub Secrets，产物私钥也不应交给排障人员。
- Runner 中会出现运行时解密后的脚本与编译内容；这是 CI 执行所必需的。工作流的 branch/actor/environment 门禁需要持续维护。
- 手动取消、Runner 崩溃、磁盘耗尽或 age/Artifact 服务不可用时，无法保证失败日志一定能成功封存。

## 解密诊断包（仅限持有临时日志私钥的人）

```bash
age -d -i log-age-key.txt -o android-logs.tar.gz android-logs-12345.tar.gz.age
tar -tzf android-logs.tar.gz
# 只在可信的临时工作目录查看，结束后安全清理
```

日志临时私钥由持有人独立保管；公开 CI 仅包含日志公钥。**更换日志公钥并不能重加密历史诊断文件**：切换前的 Run 仍需原产物私钥；切换后的诊断才能由新日志私钥解密。

**日志可能包含源码路径、访问令牌、Unity 许可证数据或签名信息；单独日志密钥并不自动保证日志脱敏。** 请把临时密钥视为敏感凭据，不要将其明文写入 GitHub、公开 Issue 或 Actions 日志，调试结束后轮换日志密钥与历史产物的访问权限。

## 当前 Android 卡顿诊断参数

为了避免重复消耗 120 分钟，在识别到 `Unity C# compilation observed` 后，若 **60 分钟内没有任何新的可识别构建阶段**，Watchdog 会封存已有诊断并退出；若 stdout、Unity CPU 与 Editor.log 都没有活动，则 30 分钟即可退出。持续静默 10 分钟时提前采集一次仅放入 age 日志包的 Editor/线程采样。该诊断超时不代表 Unity 必然死锁，也不替代编译错误、资源完整性及实机验证。

## 未完成的安全硬化

**两套工作流已实际接入** `ci/safe-extract.py`：Android 的公共脚本包与 macOS 附加包、iOS 的公共脚本包均先校验成员再解压，拒绝绝对路径、`..`、链接、特殊文件及过大的文件和文件数。相关回归测试位于 `tests/`，由无 Secrets 的 `Public CI safety checks` 工作流执行。GitHub 官方 Actions 已固定到核验过的 Commit SHA；Android 第三方 Unity CLI 安装安排在私有脚本、源码及 GitHub App Token 获取之前。

**仍未覆盖的内容：** 两份 `.age` 私有构建实现尚未解密审阅；Unity CLI Beta 安装器和 GameCI 下载的发布包仍有供应链版本/完整性漂移风险；真实 Android/iOS 构建、资源完整性、签名和实机验证仍需要集成测试。
