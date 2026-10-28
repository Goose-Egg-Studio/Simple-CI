# Simple CI / 安全构建流水线

这是 [Simple](https://github.com/Goose-Egg-Studio/Simple) 的公开 CI/CD 启动仓库。真正的 Unity 工程、音频和其它附属模块位于私有仓库；本仓库只公开 **GitHub Actions 启动流程、age 加密的构建辅助脚本及使用文档**。

> **安全边界**：公开工作流可读；构建脚本仅以 `.age` 密文保存；任何许可证、GitHub App 私钥、Android 签名文件、Apple 证书和解密私钥均不得提交。尚未配置 Secrets 前，请勿尝试正式构建。

## 基本信息

- Unity **2022.3.62f3**，主仓库 `Goose-Egg-Studio/Simple`，默认 `main`。
- Android：Ubuntu 24.04，单独构建 **APK + AAB**。
- iOS：**macOS 26 Intel + Xcode 26.6**，先导出 Xcode 工程，按需生成签名 IPA 并上传 App Store Connect/TestFlight。
- GitHub App 需获得主仓库及其所有私有 Git Submodule 的 `Contents: read`；检出使用 `submodules: recursive`。Unity Package Manager 负责 Git URL 形式的 UPM 依赖。
- Android 和 iOS 分别使用 GitHub Environments 隔离 Secrets。产物通过 **age 公钥加密**；CI 不持有产物解密私钥。

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
| `CI_AGE_IDENTITY` | 本地 `age-keygen -o ci-age-key.txt` 生成的私钥文件全文；只用于解密 `ci/sealed/secure-ci-scripts.tar.age`；在两个 Environment 中分别配置 |
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

下载 `android-*.tar.age` 或 `ios-*.tar.age` 后，在本地执行：

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
- 首次构建仍需检查 Unity/GameCI 授权、磁盘空间、macOS 26 / Xcode 26.6 和 Apple 签名的实际兼容性。
- 当前公开 CI 文件只完成静态安全检查，**尚未在 GitHub Runner 完成端到端构建验证**。
