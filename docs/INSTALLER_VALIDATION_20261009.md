# 0.2.1 一体安装包验证

日期：2026-10-09。对象：`MicForYou-0.2.1-local-alpha-macos-arm64.pkg`。
当前为 private GitHub 的 Draft 验收包，不是公开正式 Release。

## 交付对象

- 包大小：443,304,101 bytes（约 443 MB / 423 MiB）。
- SHA-256：`2fe6184f2c2a33c48312fef22b3fb9a395d18cf639ae2a584e8f7dc90f5e99af`。
- `/Applications/MicForYou.app`：0.2.1 build 4、C01 图标、独立 Python 3.12.13、推理依赖、通用模型、离线首次设置和许可／对应源码。
- `/Library/Audio/Plug-Ins/HAL/BlackHole2ch.driver`：官方 0.7.1 build 596。
- App 内 `Contents/Resources/Installers` 保留原始官方安装包，用于离线修复。
- 原始 BlackHole 包 SHA-256：`57b540f27a3e29c37e310e01bee0fdfab76733087e47f997ef9dccf851400dcf`。
- 模型与推理链路未修改；原有性能记录仍见 [0.2.0 验证](BUNDLED_APP_VALIDATION_20261009.md)，不能当作本次真实设备录音测试。

## 已通过

- 开发环境 `PYTHONDONTWRITEBYTECODE=1 uv run --no-sync pytest -q`：110 项通过。
- 新增 12 项安装行为检查：缺失／旧版安装、同版／新版跳过、二进制缺失修复；正在运行的菜单 App、音频或声音注册任务阻止覆盖；包含空格的路径、无关 Python 进程和非启动磁盘。
- Swift release build、ModelCheck、BundleCheck、StandaloneCheck 通过。
- `pkgutil --expand` 与 `--expand-full` 只读展开最终包；原始 BlackHole 组件 Payload、Bom、PackageInfo、所有 Scripts 文件 SHA-256 完全一致。
- App 安装位置固定、`relocatable=false`、原始预检查脚本保持一致。
- 从实际载荷校验模型 SHA-256、完整官方离线安装包 SHA-256、运行环境 symlink，无外部链接、个人音频、个人 ONNX、pyc 或 DLL。
- 实际载荷 App 的 deep/strict ad-hoc 签名与官方驱动签名有效；离线原始包签名为 Existential Audio Inc. (Q5C99V536K)，Apple notary trusted。组合 `.pkg` 本身无签名。
- 在实际载荷 App 中执行 Swift → 内置 Python 的首次空配置 status / setup-status；结果未就绪、STOPPED / IDLE，执行后 App 签名仍通过。
- `/usr/sbin/installer -pkg ... -target / -showChoicesXML` 是只读查询。主 App selected=1，驱动 selected=0，与本机已有官方 0.7.1 驱动一致。不同驱动版本的分支为 Installer JS 对象模拟测试，尚未在其他实体 Mac 安装验证。

构建入口：`app/MicForYouMenuBar/package_installer.sh`。
只读验收入口：`tools/bundle/verify_installer.py --pkg ... --work FRESH_DIRECTORY`。
详细机器报告保存在本机忽略的 `outputs/installer-build/verification/verification.json`，发布包另附 manifest。

## 未运行与边界

没有在本机执行管理员安装、覆盖已安装 App／驱动、重启或修改音频输入设备。
无开发工具的新 Mac 首次安装、重启后的设备发现、真实麦克风授权／45 秒注册和豆包 30 分钟验收仍待完成。
当前无 Developer ID 签名身份，组合安装包未签名或公证；原始驱动包的公证不覆盖组合包。

管理员授权和可能重启属于系统安装流程；麦克风授权、个人声音注册与输入法设备选择仍需用户完成。
本次未实现系统默认输入自动切换。暂停原音、结束释放麦克风、退出界面保留后台的既有行为保持。
M5 MacBook Air 为既有验证基线，已测试 M1 不满足实时要求；其他设备须通过 App 内置性能检查。
