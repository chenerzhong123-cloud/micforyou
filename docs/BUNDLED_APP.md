# 完整 App：安装与首次使用

0.2.1 完整安装包包含 App、arm64 Python、推理依赖、通用 REAL-TSE 权重和
经集成授权的官方 BlackHole 2ch 0.7.1。无需另装 Python、uv、Git、音频驱动
或手动下载模型。当前为 private GitHub Draft Release 验收包，尚未公开发布。
0.1.1 ZIP 是旧控制器包；0.2.0 完整 ZIP 尚不含驱动，两者均非本次一体安装包。

## 推荐设备

- macOS 14 或更高、Apple Silicon。包不支持 Intel Mac。
- M5 MacBook Air 是此前已验证基线；已测试 M1 不支持当前模型实时过滤。
- 其他芯片、内存配置和系统负载须通过 App 内置检查，不能仅按芯片代际推定支持。
- 解压后 App 约 1 GB，首次注册会额外生成个人模型和校验报告；
  建议至少预留 3 GB 可用磁盘空间。内存最低要求尚未通过独立设备测试确定。
- 接通电源，在日常工作负载下完成检查。RTF ≤ 0.80、模拟音频链路
  p95 < 400 ms 且无故障或音频欠载才会保存注册。这不包含输入法识别耗时，
  也不能替代真实麦克风／输入法的长时间验证。

## 下载、安装与设置

1. 有仓库访问权限的维护者可在 [GitHub Releases](https://github.com/chenerzhong123-cloud/micforyou/releases)
   的 `v0.2.1-local-alpha` Draft Assets 下载 `.pkg` 与 `.sha256`；对外发布后
   普通用户使用同样流程。不要将 `Source code (zip)` 当作安装包。
   在下载目录运行 `shasum -a 256 -c MicForYou-0.2.1-local-alpha-macos-arm64.sha256`。
2. 安装前先结束音频、取消声音注册并退出旧版 App。双击 `.pkg`，按系统提示授权
   管理员安装。App 固定安装到 `/Applications/MicForYou.app`，音频驱动安装到
   `/Library/Audio/Plug-Ins/HAL`。安装器不会删除个人数据，也不会自动启动 App。
   首次安装或升级驱动后按提示重启；已有同版或更高版驱动时跳过该组件。
   若 `~/Applications` 仍有旧版，请启动 `/Applications` 中的新版本。
3. 组合安装包尚未 Developer ID 签名／公证，App 为 ad-hoc 签名。
   BlackHole 原始包的签名／公证不覆盖组合安装包。若系统拦截，按
   [Apple 官方说明](https://support.apple.com/en-us/102445) 仅对确认来源的包选择“仍要打开”。
   打开新 App 的“设置”；若驱动意外缺失，可点击“安装音频组件…”运行随 App
   附带的官方离线修复安装器，重启后“刷新”，无需另行下载。
4. 选择日常麦克风，点击“注册我的声音”，允许 MicForYou 使用麦克风。
   在安静环境自然朗读 45 秒。App 会自动导出模型、校验与测试性能。
   进度显示在设置窗口；可以取消或失败后重试，旧注册不会被失败结果替换。
5. 设置成功后，在豆包的输入设备中选择 `BlackHole 2ch`。
   点击“开始过滤”，等待就绪，再使用语音输入。

暂停过滤时，原始麦克风音频继续输入，包括旁人和环境声。
点击“结束”才停止本链路并释放麦克风。退出界面会保留后台音频。
当前不自动切换系统默认输入；结束后需要时手动恢复实体麦克风。
更换声音注册前先结束；更新 App 前先结束后台音频。

## 数据、更新与许可

个人录音、个性化模型、设置及报告保存在
`~/Library/Application Support/MicForYou`，不上传到云端。
App 移动或更新后会重新定位内部资源，保留个人数据。失败的候选注册会清理；
成功的旧注册保留在 registrations 中，便于回退，可能占用额外空间。
从 0.1.1 控制器升级时需在完整 App 中重新注册一次。旧录音、模型和配置保留，
新注册通过后才切换；完整 App 不会启动旧配置引用的开发环境。

模型不是统一的单一许可：Ke Zhang 自有源码和训练参数获 Apache-2.0
书面授权；WeSpeaker ECAPA 预训练参数按上游 CC BY 4.0 保留署名。
完整声明见 App 设置中的“许可与致谢”及
[模型声明](../licenses/MODEL_NOTICES.md)。
已识别的 LGPL／MPL 组件源码、许可证和替换说明随包附带，见
[原生运行库声明](../licenses/NATIVE_NOTICES.md)。
BlackHole 的官方二进制依据另行集成授权分发，源代码与二进制许可不能混同，见
[BlackHole 声明](../licenses/BLACKHOLE_NOTICES.md)。

## 对外发布前仍待验收

- 无开发环境的新设备上，真实完成第一次授权、录音、模型准备和输入法设置。
- 真实麦克风／豆包的 30 分钟混合运行及暂停、继续、结束操作。
- 全部实际原生依赖的最终分发复核。
- Developer ID 与 Apple 公证；当前机器没有可用的签名身份。

这些限制意味着本地完整包可以继续验收，尚不能宣称公开发布已经完成。
