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

下载 `ios-*.tar.age` 后，在本地执行（Android 现在使用独立的 `.tar.gz.age` 包，见下文）：

```bash
age -d -i artifact-age-key.txt -o output.tar android-12345.tar.age
tar -tf output.tar
tar -xf output.tar
```

明文安装包和 Xcode 工程不得通过公开 Actions Artifact、Release 或 Cache 传播。iOS 上传 TestFlight 仍会由 Runner 向 Apple 提交已签名的明文 IPA。

## 操作方式与注意事项

在 **Actions** 选择 `Unity Android` 或 `Unity iOS`，使用 `workflow_dispatch` 填写 `source_ref`（建议主仓具体 Commit SHA）；iOS 初次测试先用 `export_ipa=false`。两套工作流均限制仅在受信任的原仓库、默认分支和白名单触发下运行。

- 禁止未经审查的 PR 代码在能够取得 Environment Secrets 的 Job 运行。
- 固定和定期审核第三方 Actions；确保能修改默认分支和工作流的人员可信。
- 不要把 `Library/`、明文构建产物、调试日志或本地密钥加入公开 Git 历史；`.gitignore` 不能代替人工审计。

## Android CI 构建环境与诊断（2026-10-29）

Android 工作流 `.github/workflows/android.yml` 采用 **`macos-26-intel`** 和 GameCI CLI v0.1.48 的原生 Unity Editor。旧 Linux Editor 无法正常导入工程中的 MP4，造成 Addressables 内容缺失，但 Player 可能仍返回成功。Android 保留原有 age 加密脚本以及额外的 `ci/sealed/macos-android-extra.age`，无需更换解密密钥。

**每次 Android 构建最多上传三个独立的 GitHub Actions Artifacts：**

| Artifact 名称 | 唯一的内部文件 | 解密后内容 |
| --- | --- | --- |
| `android-private-logs-<run_id>` | `android-<run_id>-logs.tar.gz.age` | `private-logs/`（Unity/Hub 原始日志、监测状态、封装状态） |
| `android-sealed-apk-<run_id>` | `android-<run_id>-apk.tar.gz.age` | `build-outputs/*.apk` |
| `android-sealed-aab-<run_id>` | `android-<run_id>-aab.tar.gz.age` | `build-outputs/*.aab` |

三个压缩包**分别**使用 `ci/artifact-recipient.txt` 指定的 age 公钥加密；公开 Actions、Artifacts 以及缓存中不会存放明文 APK、AAB、Unity 源文件或原始诊断内容。压缩包解密私钥仍只留在维护者本地。

本地解密示例（把 RUN_ID 换成实际值）：

```bash
age -d -i artifact-age-key.txt -o apk.tar.gz android-RUN_ID-apk.tar.gz.age
tar -xzf apk.tar.gz
age -d -i artifact-age-key.txt -o aab.tar.gz android-RUN_ID-aab.tar.gz.age
tar -xzf aab.tar.gz
age -d -i artifact-age-key.txt -o logs.tar.gz android-RUN_ID-logs.tar.gz.age
tar -xzf logs.tar.gz
```

如果构建失败或仅产出一种 Android 格式，会尽可能上传**独立加密诊断包**及已有的 APK/AAB；但只有完整的 APK、AAB 和诊断包均已成功上传，成功构建才算通过最终验收。

### 构建长时间无进展时

`ci/safe-progress.py` 使用独立的心跳 / watchdog 线程，不再受 Unity 原始日志持续刷屏的影响。公开 Actions 每分钟只输出固定安全状态（是否观察到 Unity/Hub、日志是否增长、磁盘是否偏低），不会打印路径、素材名、堆栈或 Unity 原始输出。详细采样数据只写入加密日志包中的 `private-logs/unity-watchdog.log`。

- **35 分钟完全没有原始日志增长**：结束构建并尝试加密诊断。
- **总构建时间超过 115 分钟**：结束构建并尝试加密诊断。
- **剩余磁盘低于 1 GiB，连续三次检查**：结束构建并尝试加密诊断。
- 诊断包会尽可能包含 Unity Hub、Unity Editor 最近的日志片段和磁盘快照，防止再出现只有心跳、无从定位的情况。

**重要：** GitHub 取消运行或 Runner 被强制回收时，`if: always()` 无法保证后续加密/上传步骤一定执行。为了获取诊断，遇到长时间卡顿应优先让 watchdog 主动超时，而不是手动点击 Cancel workflow。此监控不能证明 Unity 一定卡在安装阶段，需结合下一次的加密日志判断。

