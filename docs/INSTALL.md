# 安装 MicForYou（完整安装包）

[English](INSTALL.en.md) · [返回 README](../README.md)

完整安装包（`.pkg`）内置菜单栏 App、arm64 Python 运行环境、推理依赖、通用 REAL-TSE 权重和经集成授权的官方 BlackHole 2ch 0.7.1 驱动，无需另装 Python、uv、Git、音频驱动或手动下载模型。

**试用版本 0.2.2。** [下载安装包](https://github.com/chenerzhong123-cloud/micforyou/releases/download/v0.2.2-trial/MicForYou-0.2.2-trial-macos-arm64.pkg)。安装包尚未完成 Developer ID 签名与 Apple 公证，App 为 ad-hoc 签名；若 macOS 拦截，请按下方安装步骤处理。

## 推荐设备

- macOS 14 或更高、Apple Silicon；不支持 Intel Mac。
- MacBook Air M5 是目前唯一完成较长时间验证的基线；已测试的一台 M1 MacBook Pro 未达到实时门槛，不支持实时过滤。
- 其他芯片、内存配置和系统负载须通过 App 注册时的内置性能检查，不能仅凭芯片型号推定支持。
- 解压后 App 约 1 GB，首次注册会额外生成个人模型与报告；建议至少预留 3 GB 可用磁盘空间。内存最低要求尚未通过独立设备测试确定。
- 建议接通电源、在日常工作负载下完成注册检查。

## 下载与安装

1. 在 [试用版本下载页面](https://github.com/chenerzhong123-cloud/micforyou/releases/tag/v0.2.2-trial) 的 Assets 下载 `.pkg` 与 `.sha256`。不要把 `Source code (zip)` 当作安装包。
   在下载目录运行 `shasum -a 256 -c <安装包文件名>.sha256` 核对完整性。
2. 安装前先在旧版中点击“结束”、取消正在进行的注册并退出 App。双击 `.pkg`，按系统提示输入管理员密码。App 固定安装到 `/Applications/MicForYou.app`，音频驱动安装到 `/Library/Audio/Plug-Ins/HAL`。安装器不删除个人数据，也不会自动启动 App。
3. 首次安装或升级驱动后按提示重启 Mac；已有同版或更高版驱动时自动跳过该组件。若 `~/Applications` 仍有旧版副本，请启动 `/Applications` 中的新版本。
4. 组合安装包未做 Developer ID 签名／公证，BlackHole 原始包的签名公证不覆盖组合包。若系统拦截，按 [Apple 官方说明](https://support.apple.com/en-us/102445) 仅对确认来源的包选择“仍要打开”。
5. 若音频驱动意外缺失，打开新 App 的“设置”，点击“安装音频组件…”运行随 App 附带的官方离线修复安装器，重启后点击“刷新”，无需另行下载。

## 首次设置（声音注册）

1. 打开“应用程序”中的 MicForYou，进入“设置”。
2. 选择日常使用的麦克风。
3. 点击“注册我的声音”，按 macOS 提示允许 MicForYou 使用麦克风。
4. 在安静环境自然朗读 45 秒（开始前有 3 秒倒计时）。App 随后自动导出个人模型、校验数值一致性并测试本机性能，进度显示在设置窗口。
5. 注册过程可以取消；失败后可重试，旧的注册不会被失败结果替换。性能门槛：有效候选 RTF ≤ 0.80、模拟音频链路内部延迟 p95 < 400 ms 且无故障或音频欠载。该检查不包含豆包识别耗时。
6. 注册成功后，在豆包输入法中将输入设备选为 **BlackHole 2ch**，点击 MicForYou 的“开始过滤”，等待状态变为“正在过滤”后再开始语音输入。

日常操作（暂停、继续、结束）的语义与限制见[使用指南](USAGE.md)。

## 更新

1. 先点击“结束”并退出旧版 App（正在运行的 App／音频／注册任务会使安装预检查停止）。
2. 下载并安装新版完整 `.pkg`，再打开 `/Applications/MicForYou.app`。
3. `~/Library/Application Support/MicForYou` 中的声音注册与设置会保留；更新后先确认状态就绪，再开始过滤。
4. 从旧控制器版本（0.1.x ZIP）升级时，需在完整 App 中重新注册一次声音；新注册通过后才切换配置。

## 卸载

1. 点击“结束”，退出菜单栏 App。
2. 将 `/Applications/MicForYou.app`（以及旧 ZIP 遗留在 `~/Applications` 的副本）移入废纸篓。
3. 在豆包输入法（或系统声音设置）中把输入设备恢复为日常麦克风。
4. 配置与声音注册保存在 `~/Library/Application Support/MicForYou`，确认不再需要时可整体删除。BlackHole 驱动位于 `/Library/Audio/Plug-Ins/HAL`，如需移除请使用其官方卸载方式。

## 许可

本项目自有代码与文档采用 [Apache-2.0](../LICENSE)，署名见 [NOTICE](../NOTICE)。该许可不替代模型、运行库与官方驱动的各自条款：

- 模型不是统一的单一许可：REAL-TSE 作者自有源码与训练参数获 Apache-2.0 授权；WeSpeaker ECAPA 预训练参数按上游 CC BY 4.0 保留署名。完整声明见[模型声明](../licenses/MODEL_NOTICES.md)。
- 已识别的 LGPL／MPL 原生组件源码与许可随包附带，见[原生运行库声明](../licenses/NATIVE_NOTICES.md)。
- BlackHole 官方二进制依据另行集成授权分发，见[BlackHole 声明](../licenses/BLACKHOLE_NOTICES.md)。
