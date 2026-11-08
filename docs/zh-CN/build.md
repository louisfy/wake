# 构建与发行

## 环境

- Apple Silicon Mac，当前仅生成 arm64 安装包。
- Xcode / Command Line Tools，包含 macOS 26 SDK，Swift 6.2 或以上。
- 系统构建 Python 3 和 `zstd` 解压工具，例如通过 `brew install zstd` 安装。
- 首次构建需要访问公开 GitHub 发行地址，之后下载缓存可复用。

```sh
./script/build_and_run.sh --build-only
```

固定的运行时和同版本完整档案见 `runtime.lock.json`，下载后分别验证 SHA-256。完整档案只用于提取第三方许可证及构建元数据，应用实际使用 stripped install-only 运行时。若需更换，更新两份锁定信息并复核许可证，不能仅替换文件名。

可以用 `WAKE_PYTHON_RUNTIME` 指定具有相同目录结构及 `upstream-licenses/` 的已准备运行时；这属于本地自定义构建。公开发行使用默认的锁定运行时路径，不能借此把其他产品的私有文件打进包。

## 产物与标识

默认标识 `dev.wake.launcher`，数据目录 `~/Library/Application Support/Wake/`。与历史个人安装隔离；源码不携带个人标识、旧配置路径或本地证书指纹。

构建先映射 Swift 源路径并移除调试符号，再签名；ZIP 不保存 Finder 扩展属性、ACL 或 `__MACOSX`。检查器扫描源码与最终归档中的有限敏感模式，另需人工审查。

```text
dist/Wake-1.1-macos-arm64.zip
dist/SHA256SUMS.txt
```

`--build-only` 默认不安装。`--install` 和 `run` 才安装到 `/Applications/Wake.app`；已有同标识的 1.0 安装会原位升级。正在运行的应用不会被覆盖，标识不同的应用会保留。工作区仅保留 ZIP，避免多份 `.app` 被 Spotlight 注册。

## 本地签名与正式发行

默认 ad hoc 签名，无需读取维护者钥匙串；它适合源码自构建和本机验证，不能当成已公证的软件发布。

已有合适的 Developer ID 证书时，可使用：

```sh
WAKE_CODESIGN_IDENTITY='Developer ID Application: YOUR PUBLISHER' \
WAKE_SIGNING_MODE=release ./script/build_and_run.sh --build-only
```

发布前需按 [Apple 官方说明](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)提交公证，验证结果，并 stapling 后重新打包和生成校验和。证书、私钥、Apple 登录信息及本机钥匙串配置均不进入源码。此仓库没有自动上传公证或自动发布的脚本。

Apple 签名身份可能展示证书持有者名称。若公开二进制的隐私边界尚未确定，可先验收并发布源码，不要上传个人本地签名版。

## 检查

```sh
python3 -B script/privacy_check.py --source
python3 -B script/privacy_check.py --archive dist/Wake-1.1-macos-arm64.zip
python3 -B script/prepare_source.py
```

对真实安装检查 `codesign --verify --deep --strict`；对正式发行另检查 Gatekeeper 与公证票据。源码、单元测试、打包、真实 UI 操作及其他系统兼容性是不同的验证层次。
