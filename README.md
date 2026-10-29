# Simple CI

这是 [Simple](https://github.com/Goose-Egg-Studio/Simple) 的公开 CI/CD 启动仓库。

## 首次配置

在本仓库的 **Settings → Secrets and variables → Actions → Variables** 中创建下面四个 *Repository variables*：

| Variable | 内容或来源 |
| --- | --- |
| `CI_REPOSITORY` | `Goose-Egg-Studio/Simple-CI` |
| `SOURCE_REPOSITORY` | `Goose-Egg-Studio/Simple` |
| `SOURCE_APP_CLIENT_ID` | GitHub App 设置页的 Client ID |
| `ALLOWED_BUILD_ACTORS` | 允许发起构建的用户名 JSON 数组，例如 `["YourLogin"]` |

在 **Settings → Environments** 创建 `android-build`、`ios-build`，将对应的 **Environment secrets** 分别写入，不要把平台签名材料放到仓库级 Secrets。建议配置允许分支与审批规则。

### 两个平台都需要的 Environment Secrets

| Secret | 如何获取 |
| --- | --- |
| `CI_AGE_IDENTITY` | 本地生成的私钥文件全文；只用于解密脚本；在两个 Environment 中分别配置 |
| `SOURCE_APP_PRIVATE_KEY` | 在 GitHub → Settings → Developer settings → GitHub Apps 中创建 App，给目标私仓及附属仓 `Contents: read`，安装至对应组织，在 App 设置页生成 PEM 私钥并将**全文**放入 Secrets |
| `UNITY_LICENSE` | Unity 激活后提供的原始 `.ulf` 文件内容；**不用 Base64** |
| `UNITY_EMAIL` / `UNITY_PASSWORD` / `UNITY_SERIAL` | 按 Unity 授权模式及 GameCI 需求配置；不要向公开仓库上传账号或授权材料 |

GitHub App 应只授权真正需要的仓库；获取到的安装令牌是短期令牌，Workflow 不应将其持久写入公开产物。

### Android 专用（`android-build`）

| Secret | 如何获取 |
| --- | --- |
| `ANDROID_KEYSTORE_BASE64` | 将已有用于发布的 Android `.jks` / `.keystore` **完整文件**进行 Base64 编码 |
| `ANDROID_KEYSTORE_PASS` | Keystore 密码，原文 Secret |
| `ANDROID_KEYALIAS_NAME` | 签名 Key Alias |
| `ANDROID_KEYALIAS_PASS` | Alias 对应的 Key Password，原文 Secret |

可用 `keytool -genkeypair -v -keystore release.jks -alias simple -keyalg RSA -keysize 3072 -validity 10000` 生成测试密钥，但已有正式发布应用**必须继续使用现有签名密钥**。

### iOS 专用（`ios-build`，仅在 `export_ipa=true` 时需要完整配置）

| Secret | 如何获取 |
| --- | --- |
| `IOS_P12_BASE64` | Apple Developer 证书与对应私钥导出为 `.p12`，将文件 Base64 |
| `IOS_P12_PASSWORD` | 导出 P12 时设置的密码 |
| `IOS_PROFILE_BASE64` | Apple Developer → Certificates, Identifiers & Profiles → Profiles，下载分发 Provisioning Profile 并 Base64 |
| `IOS_TEAM_ID` | Apple Developer Membership 中的 Team ID |
| `IOS_BUNDLE_ID` | 与 Apple Developer / App Store Connect 应用一致的 iOS Bundle ID |
| `ASC_KEY_ID` | App Store Connect → Users and Access → Integrations → App Store Connect API 的 Key ID |
| `ASC_ISSUER_ID` | 同页面 Issuer ID |
| `ASC_P8_BASE64` | 下载的 API 私钥 `.p8` 文件 Base64（Apple 通常只允许下载一次） |

Windows PowerShell 文件 Base64 示例：

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("certificate.p12")) | Set-Clipboard
```

**Base64 是编码不是加密**；只有 GitHub Secrets 负责保护值。任何密码、PEM 私钥、`.ulf` 许可证都应按 Workflow 定义存储，不必统一 Base64。

## 两套 age 密钥与产物解密

本仓库存放的 `ci/recipient.txt` 仅是**脚本加密公钥**；CI Runner 需读取 `CI_AGE_IDENTITY` 来执行密文内的脚本。

`ci/artifact-recipient.txt` 是**构建产物加密公钥**，Runner 只有公钥，没有产物解密权限。产物解密私钥必须留在授权维护者本机，不应放入任何 GitHub Secret。

下载 `ios-*.tar.age` 后仍使用下方原有解密流程；Android 新格式为各自独立的 `.tar.gz.age`：

```bash
age -d -i artifact-age-key.txt -o android-apk.tar.gz android-apk-12345.tar.gz.age
tar -tzf android-apk.tar.gz
tar -xzf android-apk.tar.gz
# Android AAB / 诊断日志包仅需将上述文件名分别改为 android-aab / android-logs
```

明文安装包和 Xcode 工程不得通过公开 Actions Artifact、Release 或 Cache 传播。iOS 上传 TestFlight 仍会由 Runner 向 Apple 提交已签名的明文 IPA。

## 操作方式与注意事项

在 **Actions** 选择 `Unity Android` 或 `Unity iOS`，使用 `workflow_dispatch` 填写 `source_ref`（建议主仓具体 Commit SHA）；iOS 初次测试先用 `export_ipa=false`。两套工作流均限制仅在受信任的原仓库、默认分支和白名单触发下运行。

- 禁止未经审查的 PR 代码在能够取得 Environment Secrets 的 Job 运行。
- 固定和定期审核第三方 Actions；确保能修改默认分支和工作流的人员可信。
- 不要把 `Library/`、明文构建产物、调试日志或本地密钥加入公开 Git 历史；`.gitignore` 不能代替人工审计。

## Android CI 构建环境（2026-10-29 更新）

Android 工作流 `.github/workflows/android.yml` 使用 **`macos-26-intel`**（macOS 26 / Intel x64，标准 GitHub-hosted runner）。原因是 Unity 2022.3 的 Linux Editor 无法导入项目中的 MP4 视频，导致 Addressables 打包失败，但原生 Player Build 仍可能报告成功。

- 使用 **GameCI CLI v0.1.48 的 macOS 原生 Unity Editor/Hub 构建**，不使用 Linux Docker 镜像。
- 原有 `ci/sealed/secure-ci-scripts.tar.age` 保留不变；另附同一公开接收方密钥加密的 `ci/sealed/macos-android-extra.age`，包含 macOS 构建入口和 Unity Editor CI 构建方法。无需配置新的 Secret。
- Unity 构建前显式执行 Addressables 内容构建，并校验自定义加密 bundle 清单；APK/AAB 上传前还会检查包内的本地 bundle 与 manifest。失败只上传 age 加密诊断，不把完整 Unity 日志或未加密安装包公开。
- macOS 标准 Runner 的磁盘和内存可能不足以同时安装 Unity、Android 模块、导入全部素材；因此第一次迁移仍需通过实际运行验证，不能仅凭 YAML 静态校验断言成功。
- Android 成功构建将上传 **3 个相互独立的 age 加密压缩 Artifact**：`android-apk-sealed-<run_id>`、`android-aab-sealed-<run_id>`、`android-logs-sealed-<run_id>`。每个 Artifact 只包含一个 `.tar.gz.age`，分别是 `Simple.apk`、`Simple.aab`、`private-logs/`。失败时不会发布不完整 APK/AAB，但仍尽力上传独立的加密诊断包。


### Android 构建健康检查与失败隔离

新版本的安全监控脚本独立于 Unity 原始日志读取循环，每 60 秒在公开 Actions 日志输出固定格式的心跳，并把详细指标写入**仅包含在加密诊断 Artifact 中**的 `private-logs/health.jsonl`。记录包括 Unity/GameCI 进程数量（仅按进程名统计，不采集命令行）、日志增长、磁盘剩余空间、最近识别的构建阶段及距离该阶段的耗时。不公开项目资源名、原始日志、命令行、工作目录或 Secret 值。

为了避免类似 Run 40823348411 出现长时间无阶段进展的情况，当前 Android 监控默认规则：连续 45 分钟既没有 Unity 原始日志增长、也未观察到 Hub 临时下载文件增长或明显磁盘写入、120 分钟没有识别到新的构建阶段，或磁盘剩余低于 1.5 GiB，都会主动中止构建并尽力进入诊断加密上传。这些限制是排障保护阈值，并不表示 Unity 超过该时间一定死锁。识别器本身依赖固定关键词，部分合法 Unity 日志可能不会触发阶段变化。

`if: always()` 只提供 **best-effort** 日志收集：手动取消、Runner 强制关闭、磁盘耗尽或 age 不可用时，GitHub 不保证诊断包成功上传。排查长时卡住时，建议让健康检查主动失败并走完收尾流程，而非直接取消 Run。每个加密包使用同一个公开 `ci/artifact-recipient.txt` 接收方；解密私钥依旧不应进入 GitHub。

### Unity Hub 安装阶段排障（2026-10-29）

在 Run `40839715030` 中，GameCI CLI v0.1.48 成功通过 Homebrew 安装 Unity Hub 3.21.0，但 Unity Hub 在无界面安装 2022.3.62f3 的 Android SDK/NDK 子模块时停止输出，直到诊断监控触发超时。没有证据表明 Unity Editor 已启动、项目被导入或 Addressables 已开始构建。磁盘剩余约 128 GiB，因此该次故障并非磁盘空间耗尽。

为了诊断 Unity Hub 自身而不是只看 Editor.log，Android 诊断终结器现在把 `~/Library/Application Support/UnityHub/logs` 中最近最多 8 个普通文本/JSON 日志，每个末尾最多 4 MiB，复制到 **仅 age 加密上传** 的 `private-logs/unity-hub/`。同时生成 `private-logs/hub-install-state.json`，只记录 Editor 和 Android Build Support/SDK/NDK/OpenJDK 是否存在的布尔值。公开 Actions 心跳把 `editor=` 与 `hub=` 进程分别显示，以避免将 Unity Hub Helper 误判为 Editor 进程。Hub 日志可能包含敏感账号信息，仍须保护产物解密私钥，切勿直接公开解密后的日志。

这只是可观测性修复，**尚未证明 Unity Hub 3.21.0 安装卡顿的具体原因**。下一轮应先分析加密的 Hub 日志，再决定是否升级 Hub、调整子模块安装方式或切换安装路径。

### Hub 下载活动监测修正（Run 40845510393）

最新加密日志明确显示 Unity Hub 3.21.0 已调用 2022.3.62f3 的下载管理器，下载源与磁盘验证均通过；Editor 的下载状态变为 `downloading`。其内部日志在启动下载后不再增长。健康记录表明 T+25m 到 T+26m 间可用磁盘突然减少约 0.82 GiB，**可能是下载仍在进行**（无法仅凭全盘变化证明归属于 Unity）。旧的 25 分钟标准输出超时可能在安装仍有活动时过早终止构建，不能把下载日志安静等同于真正死锁。

新的独立监控还统计 macOS 临时目录中 `unityhub*` 下载目录的大小变化（仅记录字节数，不上传文件内容或路径），并将显著磁盘占用增长作为粗略活动提示。公开日志仅显示 `installer-io=active/quiet`。详细的 `hub_temp_bytes`、`hub_temp_growth_bytes`、`disk_drop_gib`、`last_observed_activity_seconds` 保存在 age 加密的 `health.jsonl`。这只能减少误报：如果 Hub 将文件写到其他位置或磁盘变化来自其他进程，仍然需要结合 Unity Hub 日志判断。

这是 **watchdog 误杀风险的修复，不是 Unity Hub 下载问题本身已解决的证明**。建议下一次观察 Hub 自身下载进度、实际安装完成标记；若仍无法安装，再考虑改用 Unity 官方独立 CLI 或预安装 Editor + Android 模块。不要因为超出 25 分钟没有普通日志就手动取消构建。

## Android 最新安装路线：自包含 Editor（2026-10-30）

在 2026-10-30 的一次新运行中，官方独立 Unity CLI 已完成 bootstrap，但此前使用 `unity install-path --set/--get` 的全局目录配置阶段立即失败，尚未进入 Editor 下载。**目前未拿到这次运行的解密日志，不能确认具体失败于哪个旧目录配置命令。**

Unity CLI 1.0.0-beta.14 已增加 `unity install --download-directory <dir>` 与 `unity install-modules --download-directory <dir>`，可将 Editor 和模块完整安装到一个自包含目录，完全不修改全局 Hub 安装路径。CI 现在使用这条官方路径：

1. 官方 Beta 安装器提供 Unity CLI，检查 CLI 是否支持 `--download-directory`，不支持则立即分类失败。
2. 用 `unity install 2022.3.62f3 --changeset 96770f904ca7 --architecture x86_64 --download-directory "$RUNNER_TEMP/simple-unity-editors/2022.3.62f3" --yes --accept-eula` 安装 Editor。
3. 用 `unity install-modules --download-directory "$RUNNER_TEMP/simple-unity-editors/2022.3.62f3" --module android --child-modules --accept-eula` 添加 Android SDK/NDK/OpenJDK；不再依赖 `-e`（Unity 1.0.0-beta.15 更改过其短选项含义）。
4. **只有上述全部完成并通过本地完整性检查后**，才通过 `sudo -n` 创建 `/Applications/Unity/Hub/Editor/2022.3.62f3` 的**单个版本符号链接**，以便 GameCI v0.1.48 复用现有 Editor；不替换 Editor 根目录、不覆盖其他版本、不更改全局 `install-path`。
5. 继续原来的 GameCI 私有构建及三份独立 age 加密产物（APK、AAB、日志）。

此路线只解决**全局安装路径配置容易失败**这类问题，尚未在真实 macOS Runner 上完成下载、Android 模块安装和 APK/AAB 产物验证。历史路径配置方案在下面保留，仅供故障追溯，**不再是当前执行方案**。参见 [Unity CLI 官方发行说明](https://docs.unity.com/en-us/unity-cli/release-notes)。

---

## Android 安装链路切换：新版独立 Unity CLI + 用户可写目录（2026-10-29）

**最新确认的根因（Run 40905778356）：** 解密日志 `private-logs/unity-cli-editor-detail.log` 明确显示 `Access to the path '/Applications/Unity/Hub/Editor' is denied.`。在此之前，旧 CLI 的 `install-path --set` 曾输出 `This directory does not exist.`，但没有成功设置编辑器目录。受保护的系统路径写权限导致 Editor 安装立即失败，这一次没有进入下载阶段，也与 Unity 项目、Addressables 无关。

同时，诊断确认此前 Homebrew cask 提供的是 **Unity CLI 1.0.0-beta.6**；Unity 于 2026-10-21 发布了 beta.14，其间对安装路径、模块安装、无交互提权等进行了修复。为避免旧 cask 的版本滞后：

1. 使用 **Unity 官方 HTTPS 安装脚本** `https://unity.com/install.sh` 和 `UNITY_CLI_CHANNEL=beta` 安装 CLI，独立保存到 `$RUNNER_TEMP/simple-unity-cli/bin/unity`。不再使用 Homebrew 的旧 beta.6。运行时记录版本，对早于 beta.14 的 1.0.0 Beta 版本拒绝继续。
2. 创建用户拥有、权限为 `0700` 的 `$RUNNER_TEMP/simple-unity-editors`，将 CLI 的 `install-path` 配置为该目录，并在继续前读回验证。**不**对 `/Applications` 执行 `chmod 777` 或广泛 `chown -R`。
3. GameCI v0.1.48 在 macOS 上固定检查 `/Applications/Unity/Hub/Editor/<version>/Unity.app`。因此仅在标准路径为空时，以 `sudo -n` 建立从 `/Applications/Unity/Hub/Editor` 到上述用户可写目录的**符号链接**；已有非空安装目录或未知符号链接时立即失败，不删除或覆盖已有安装。
4. 使用独立 Unity CLI 分两段安装：先执行带固定 changeset 的 **Unity 2022.3.62f3 x86_64 Editor 本体安装**，再执行 `unity install-modules -e 2022.3.62f3 -m android --child-modules --accept-eula` 安装 Android Support、SDK、NDK、OpenJDK。
5. 验证标准路径能够看到 Editor 二进制及全部 Android 模块后，才调用原有 age 解密的 GameCI 构建脚本。GameCI 可能仍会安装 Hub 应用以兼容其内部接口，但因 Editor 已存在，理论上不会再调用旧 Hub 安装器下载 Editor。

**保密约束不变：** CLI 下载器、安装器的 stdout/stderr 只写入 `private-logs/unity-cli-install.log`，细分到 `unity-cli-editor-detail.log` 与 `unity-cli-modules-detail.log`。安装路径配置与安装器帮助同样只进入独立的 age 加密诊断 Artifact；公开 Actions 日志仅有白名单健康提示。APK、AAB、诊断日志继续是三份**独立 age 加密归档**。

**注意：** 这是针对已经确认的目录权限错误及旧版 CLI 的修复，尚未在全新的 GitHub macOS Runner 上验证完整 Editor/Android 安装及 APK/AAB 构建。Unity CLI 仍处于实验性阶段；官方安装脚本取当前 beta 频道版本，其上游代码会随发布更新，需要按供应链策略审计。

参考：[Unity 官方 CLI 安装方式](https://docs.unity.com/en-us/unity-cli/use-unity-cli)、[官方 CLI 发行说明](https://docs.unity.com/en-us/unity-cli/release-notes)、[Unity CLI 命令参考](https://docs.unity.com/en-us/unity-cli/unity-cli-reference)。
