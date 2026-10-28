# 机密构建日志（安全收集）

本更新把原本直接运行的 `game-ci/unity-builder` 步骤改成封装在 age 加密脚本中的 `game-ci` CLI 命令。私有源码检出、项目校验、Unity 编译、iOS 签名与上传的标准输出和错误输出保存在 Runner 临时目录，**不主动打印至公开 Actions 控制台**。

## 加密包格式

成功：`build-outputs/`（APK+AAB 或 IPA/Xcode）与 `private-logs/` 一起加密。失败：至少 `private-logs/` 加密，可能包含已有的部分构建输出。每次都使用 `ci/artifact-recipient.txt` 的 **age 产物公钥**，CI 不持有产物解密私钥。

解密：`age -d -i artifact-age-key.txt -o build.tar android-123.tar.age`，然后 `tar -tf build.tar` 查看。**请只在可信电脑上解密**。

GitHub 必须展示 Job/Step 名称、结果、运行时间、Runner 信息以及个别官方 Action 的启动输出。无法保证 OS 强制终止、超时、Runner 损毁、磁盘写满、缺失 age、GitHub Artifact 服务故障时仍能产生日志包。也无法保证所有第三方 Action 本身没有输出私仓信息：本版将最敏感的源码拉取、Unity 和 Xcode 输出封装在重定向命令中。

注意：本版首次采用独立 `game-ci/cli` 执行构建（而非旧 `unity-builder@v4`），仍需真正的 Android 和 macOS 构建验证。CLI 安装步骤在私有源码检出后进行，应避免上游安装脚本读取私有目录；可进一步前移至源码检出之前。正式启用前审核和固定外部 Action 的 Commit SHA。
