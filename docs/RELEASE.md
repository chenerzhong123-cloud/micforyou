# GitHub 发布准备

当前已构建 0.2.1 一体安装 Alpha，内置 App、Python、推理依赖、通用模型和经集成授权的官方 BlackHole 2ch；首次使用由 App 引导声音注册。当前仓库仍为 private，尚无已发布完整 Release。完整包作为 `v0.2.1-local-alpha` Draft Release 提供维护者验收，未完成下列发布条件。提交与推送源码、文档不会改变仓库可见性或自动公开安装包。

## 本地交付

```bash
./app/MicForYouMenuBar/package_release.sh
```

产物位于 `outputs/releases/`，包含本机架构的 `.app.zip` 与 `.sha256`。ZIP 只有 App 和双语 `INSTALL.txt`，不包含 Python 环境、权重、声音注册或运行报告。该命令只生成控制器外壳；历史 0.1.1 包同样只有控制器。此包为 ad-hoc 签名、未公证。

完整包构建使用独立 CPython 3.12（可由 `uv python install 3.12 --install-dir outputs/bundle-build/python` 准备），安装 `requirements-bundle.lock` 后执行：

```bash
uv pip install --target outputs/bundle-build/cmake cmake==4.4.4
PYTHON_ROOT/bin/python3.12 -B tools/bundle/prepare_native.py \
  --sources outputs/bundle-build/sources \
  --cmake outputs/bundle-build/cmake/cmake/data/bin/cmake \
  --output outputs/bundle-build/native
./app/MicForYouMenuBar/package_complete.sh PYTHON_ROOT REAL_TSE_REPO WESPEAKER_PACKAGE
```

固定源码版本与原始 checkpoint hash 会在构建时检查。完整包内置通用模型、离线推理源码、Python、许可与版本清单；不包含个人声音和个性化模型。普通 venv 不能作为 PYTHON_ROOT。安装依赖时仅对专用构建 Python 使用 `uv pip install --break-system-packages --python ... -r requirements-bundle.lock`，不得修改系统 Python。

一体安装包使用上述完整运行环境，再提供固定版本的官方驱动包：

```bash
curl -fL https://existential.audio/downloads/BlackHole2ch-0.7.1.pkg -o BlackHole2ch-0.7.1.pkg
./app/MicForYouMenuBar/package_installer.sh PYTHON_ROOT REAL_TSE_REPO WESPEAKER_PACKAGE BlackHole2ch-0.7.1.pkg OUTPUT_ROOT
```

构建器检查官方包 SHA-256 与签名身份，保留原始组件 Payload/Bom/脚本，并将完整 App 和驱动组成 `.pkg`；另附 checksum、manifest 和双语说明。输出目录须全新。App 安装位置固定 `/Applications`，正在运行的 App／音频／注册任务会使预检查停止。驱动同版或更新版跳过，缺失或旧版安装后按官方要求重启。安装脚本不修改输入设备、不启动录音、不删除用户数据。组合包目前无签名／公证，原始驱动的公证不覆盖它。

当前包仅供本地 Alpha 验收，公共发布条件见下文。用户指南：[中文](BUNDLED_APP.md) / [English](BUNDLED_APP.en.md)。

最新宣传片和预览图已加入 `docs/media/`，中英文 README 使用仓库内相对链接；随源码推送后即可由有仓库访问权限的用户下载。它们不依赖开发机 localhost。

## 发布前需完成的事项

完整 App 的模型授权结论与实施方案见 [模型许可与完整 App 分发核查](MODEL_DISTRIBUTION_AUDIT.md)。已取得作者自有部分 Apache-2.0 授权，第三方 ECAPA 按官方 CC BY 4.0 保留署名。本地完整包已生成；历史外壳 ZIP 不能标为完整包。

1. 完成本次新增行为的真实麦克风、豆包、断链与 30 分钟混合运行验收，结果写入 `PAUSE_PASSTHROUGH_VALIDATION.md`。保留模型质量边界。
2. 确认目标受众：private 仓库仅向已有访问权限的人分发；面向所有用户时，由仓库所有者决定可见性或单独分发仓库，并调整双语 README 的下载状态。
3. 明确本项目代码与品牌资源的分发许可；当前仓库没有项目 LICENSE。通用模型随完整 App 内置，各部分来源与许可分别保留。已识别 LGPL／MPL 组件源码随包交付，全部实际原生库仍需最终分发复核。
4. 面向普通用户分发前，推荐配置 Developer ID 签名与 Apple 公证，以减少首次打开阻拦。当前极客测试包仍明确说明 ad-hoc 状态。
5. 提交经审查的源码、双语说明和视频，创建 Experimental Alpha prerelease，上传完整 `.pkg`、checksum、manifest 和双语说明、宣传片；只声明已验证的架构。README 的 Release 链接使用发布后的真实资产。

## 0.1.1 更新说明草稿

- 暂停过滤后原始麦克风声音继续送往输入法；继续在同一音频进程与 Stream 内恢复过滤。
- 结束才释放麦克风；暂停期间不能换麦或重新注册；退出界面保留音频。
- 新增本机专属控制 socket、模式确认、旧状态兼容和迟到输出隔离。
- 修复首次 configure 不保存与 set-policy 被旧值覆盖的问题。
- 增加中英文 GitHub 安装指南、独立模型环境 requirements、最新宣传片和 C01 品牌资源。
- 已验证：自动测试、Swift build / model check、本机签名与 ZIP、真实 ONNX 合成输入模式切换。真机与豆包新行为验收状态见验证记录。
