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

## Android Run #36：Unity 构建成功但 GameCI 误判失败

[Run #36](https://github.com/Goose-Egg-Studio/Simple-CI/actions/runs/41173204593) 的临时日志密钥解密结果显示：Unity 生成约 690 MiB 的 `Game.apk`，并输出 `SIMPLE_CI_ADDRESSABLES_VERIFIED`、`Build Finished, Result: Success.`、`SIMPLE_CI_PLAYER_VERIFIED`，Unity batchmode 正常退出。由于 GameCI CLI v0.1.48 的 macOS 原生校验器只接受字面 `Build succeeded!` 或符合格式的 `Build results` 统计块，而实际 wrapper 只输出 `Build succeeded`（无叹号），其 `UnityBuildValidation.validateBuild` 报错，导致最终工作流误判为失败。证据来自 [GameCI v0.1.48 源码](https://github.com/game-ci/cli/blob/v0.1.48/src/model/unity/build-validation/unity-build-validation.ts)。

新增 `ci/fix-sealed-macos-gameci-result.py`：**只修改 Runner 解密后的临时 C# helper**，并且只在原本表示 Player 已验证成功的 `Debug.Log("SIMPLE_CI_PLAYER_VERIFIED")` 中增加字面 `Build succeeded!`，保留原有阶段标志。不覆盖 GameCI 退出码，不对不成功的 Unity 构建打印成功，失败分支也不被修改。源文件布局、日志所在行或目标路径不匹配时 fail-closed。修改前原始 `.age` 包及私有 Unity 源码不受影响。

该修复的 unit tests 和公开脚本安全审计通过；**仍需完整真实构建验证** APK/AAB 的密封上传和 Android 设备上的音乐、资源、交互。Run #36 的 690 MiB APK 只存在于已销毁的临时 Runner，不会自动出现在该失败 Run 的 Artifact 中；失败 Run 上传的只有加密诊断。

## Android Run #37：APK 成功后 AAB 激活阶段项目路径失效

[Run #37](https://github.com/Goose-Egg-Studio/Simple-CI/actions/runs/41181533837) 已完成 APK Player 构建，`SIMPLE_CI_PLAYER_VERIFIED | Build succeeded!` 与 `SIMPLE_CI_PHASE=android_apk_done` 均已记录，`Game.apk` 约 690 MiB。接下来的 AAB 立即失败，但不是 Unity 授权拒绝：日志在 LicensingClient 成功激活授权后输出 `Couldn't set project path to:`，而 GameCI 错误地归类为 `License`。

已确认 [GameCI v0.1.48 macOS entrypoint](https://github.com/game-ci/cli/blob/v0.1.48/dist/platforms/mac/entrypoint.sh) 在第一个构建完成时执行 `rm -r "$ACTIVATE_LICENSE_PATH"`，删掉随 CLI 发布的 `dist/BlankProject`；第二次执行 `mkdir -p` 只能恢复空目录。空目录没有 `ProjectSettings/ProjectVersion.txt`，因此 Unity 在 AAB 的第二轮激活时无法接受 `-projectPath`。

修复脚本 `ci/fix-gameci-macos-activation-project.py` 只修补临时 Runner 内**已安装的 GameCI v0.1.48 入口脚本**，保留正常构建完成后的 `BlankProject`，仍执行原来的许可证归还。修复前校验内置 `ProjectVersion.txt` 及预期清理语句数量；源文件版本不匹配、目录缺失或符号链接时直接退出，避免误修改上游未知版本。补丁还通过 `bash -n` 验证并保留入口脚本执行权限。

这不是跳过许可证激活、也不是忽略失败退出码。AAB 仍将正常激活、构建及验证。此时 **AAB 未完成新的真实构建验证**；如果后续 AAB 成功，再分别校验与加密上传 APK、AAB，最后进行游戏音乐资源和操作的实机验证。

## 未完成的安全硬化

**两套工作流已实际接入** `ci/safe-extract.py`：Android 的公共脚本包与 macOS 附加包、iOS 的公共脚本包均先校验成员再解压，拒绝绝对路径、`..`、链接、特殊文件及过大的文件和文件数。相关回归测试位于 `tests/`，由无 Secrets 的 `Public CI safety checks` 工作流执行。GitHub 官方 Actions 已固定到核验过的 Commit SHA；Android 第三方 Unity CLI 安装安排在私有脚本、源码及 GitHub App Token 获取之前。

**仍未覆盖的内容：** 两份 `.age` 私有构建实现尚未解密审阅；Unity CLI Beta 安装器和 GameCI 下载的发布包仍有供应链版本/完整性漂移风险；真实 Android/iOS 构建、资源完整性、签名和实机验证仍需要集成测试。
