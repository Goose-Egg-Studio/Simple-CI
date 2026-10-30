# Simple-CI 机密日志与产物保护（2026-10-30）

此仓库是公开 CI 启动器，私有源码检出、Unity 编译、签名与 iOS 上传逻辑由 age 加密的实现驱动。

## Android 产物

Android 的 APK、AAB、诊断日志分别打包，并用 `ci/artifact-recipient.txt` 中的产物接收方公钥**独立 age 加密**。构建成功后预期出现：

- `android-apk-sealed-<run_id>`：`android-apk-<run_id>.tar.gz.age`
- `android-aab-sealed-<run_id>`：`android-aab-<run_id>.tar.gz.age`
- `android-logs-sealed-<run_id>`：`android-logs-<run_id>.tar.gz.age`

若构建失败，不应上传不完整的 APK/AAB；日志只做 best-effort 加密收集。脚本对 APK/AAB 做 ZIP 及 Manifest 结构检查，但**完整资源、签名、可运行性必须由加密构建逻辑和实体机验证**。

## iOS 产物

iOS 当前仍使用一个 `ios-<run_id>.tar.age` 加密包，其中可能包含 `private-logs/` 和已有的 `build-outputs/`；成功签名且上传 TestFlight 的行为由私有脚本负责。**当前 iOS 工作流尚未接入 Android 的安全心跳监控**。

## 日志保护边界

- Unity / Xcode 的原始 stdout、stderr 仅进入 Runner 的私有临时目录，不直接发到公开 Actions 控制台。
- Android 监控公开固定的阶段、心跳与失败类别，不公开文件名、源码、许可证及构建原始日志。
- `ci/recipient.txt` 用于**私有 CI 实现**，`ci/artifact-recipient.txt` 用于**构建产物与日志**。二者是不同的 age 公钥。产物私钥不得放入 GitHub Secrets。
- Runner 中会出现运行时解密后的脚本与编译内容；这是 CI 执行所必需的。工作流的 branch/actor/environment 门禁需要持续维护。
- 手动取消、Runner 崩溃、磁盘耗尽或 age/Artifact 服务不可用时，无法保证失败日志一定能成功封存。

## 解密示例

```bash
age -d -i artifact-age-key.txt -o android-logs.tar.gz android-logs-12345.tar.gz.age
tar -tzf android-logs.tar.gz
tar -xzf android-logs.tar.gz
```

只在可信设备解密；不要上传 age 私钥或未经脱敏的许可证、凭据日志。

## 未完成的安全硬化

公共辅助脚本 `ci/safe-extract.py` 可拒绝路径穿越、符号链接与超大 tar 成员，但**现有 Android/iOS Workflow 的解封步骤尚未改用它**，仍直接调用 `tar -xzf`。在工作流变更获批前，不应声称这个防护已经生效。两份 `.age` 私有构建实现目前也未在本次公开源码审计中解密审阅。
