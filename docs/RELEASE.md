# GitHub 发布准备

当前建议：通过 GitHub 提供源码与菜单栏 App 外壳，模型由用户自行准备。当前仓库仍为 private，尚无 Release。提交与推送源码、文档和宣传片不会改变仓库可见性，也不会自动创建 Release 或发布安装包。

## 本地交付

```bash
./app/MicForYouMenuBar/package_release.sh
```

产物位于 `outputs/releases/`，包含本机架构的 `.app.zip` 与 `.sha256`。ZIP 只有 App 和双语 `INSTALL.txt`，不包含 Python 环境、权重、声音注册或运行报告。菜单栏 App 的实际版本为 0.1.1，发布标签可采用 `v0.1.1-alpha`。此包为 ad-hoc 签名、未公证。

最新宣传片和预览图已加入 `docs/media/`，中英文 README 使用仓库内相对链接；随源码推送后即可由有仓库访问权限的用户下载。它们不依赖开发机 localhost。

## 发布前需完成的事项

1. 完成本次新增行为的真实麦克风、豆包、断链与 30 分钟混合运行验收，结果写入 `PAUSE_PASSTHROUGH_VALIDATION.md`。保留模型质量边界。
2. 确认目标受众：private 仓库仅向已有访问权限的人分发；面向所有用户时，由仓库所有者决定可见性或单独分发仓库，并调整双语 README 的下载状态。
3. 明确本项目代码与品牌资源的分发许可；当前仓库没有项目 LICENSE。模型的来源与条件单独处理，不随 App 重新打包。
4. 面向普通用户分发前，推荐配置 Developer ID 签名与 Apple 公证，以减少首次打开阻拦。当前极客测试包仍明确说明 ad-hoc 状态。
5. 提交经审查的源码、双语说明和视频，创建 Experimental Alpha prerelease，上传本机构建 ZIP、checksum、宣传片；只声明已验证的架构。README 的 Release 链接使用发布后的真实资产。

## 0.1.1 更新说明草稿

- 暂停过滤后原始麦克风声音继续送往输入法；继续在同一音频进程与 Stream 内恢复过滤。
- 结束才释放麦克风；暂停期间不能换麦或重新注册；退出界面保留音频。
- 新增本机专属控制 socket、模式确认、旧状态兼容和迟到输出隔离。
- 修复首次 configure 不保存与 set-policy 被旧值覆盖的问题。
- 增加中英文 GitHub 安装指南、独立模型环境 requirements、最新宣传片和 C01 品牌资源。
- 已验证：自动测试、Swift build / model check、本机签名与 ZIP、真实 ONNX 合成输入模式切换。真机与豆包新行为验收状态见验证记录。
