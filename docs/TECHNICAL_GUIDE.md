# MicForYou 技术说明

[English](TECHNICAL_GUIDE.en.md) · [用户指南](../README.md)

本文记录当前 0.2.1 测试版的性能依据、音频行为、本机数据、源码安装与分发细节。日常使用请先阅读用户指南。

## 硬件与性能要求

**当前推荐以已验证的 MacBook Air M5 为运行基线。已测试的 M1 未达到当前模型的实时要求，不推荐用于过滤。** 其他设备即使芯片更新或规格更高，也需要先通过本机性能检查；目前不能仅凭型号保证延迟可接受。

| 项目 / 设备 | 当前要求与验证结果 |
| --- | --- |
| 系统与架构 | 菜单栏界面要求 **macOS 14+**；完整包仅支持 **Apple Silicon（arm64）**，不支持 Intel。 |
| MacBook Air M5 | 此前通过 [30 分钟运行验证](MAC_A_NEXT_STAGE.md)，bridge 内部音频延迟 p95 约 **260 ms**。这是当前已验证基线，实际表现仍受负载和电源状态影响。 |
| MacBook Pro M1（已测试设备） | 当前 REAL-TSE checkpoint 的最佳有效 RTF 为 **1.052**，处理速度低于实时要求，不能持续跟上音频输入。当前不支持该设备上的实时过滤。 |
| 其他 Mac | 尚无足够验证，包括其他代际和 Pro / Max / Ultra 型号。具备相当或更强持续处理能力的设备可以作为候选，但不能跳过性能检查。 |
| 磁盘与内存 | 解压后 App 约 1 GB，建议预留至少 3 GB 可用空间用于注册模型和报告。最低内存要求尚未通过独立设备测试确定。 |

完整 App 在声音注册时自动进行本机性能检查：推荐候选的 **RTF ≤ 0.80**（处理耗时 / 音频时长，保留至少 20% 吞吐余量），配速复核的 **bridge 内部延迟 p95 < 400 ms**，且无 FAULT 或音频欠载（underrun）。建议接通电源，并在日常工作负载下复核；后台重负载可能让同一台机器从达标变为不达标。源码用户可按 [安装指南第 5 节](INSTALL.md) 手动验证。详见 [性能指南](PERFORMANCE_GUIDE.md) 和 [M1 测试记录](MAC_B_COREML_THREAD_RECHECK_RESULTS_20260918.md)。

**上述延迟是 MicForYou 音频链路的指标，不包含豆包识别及文字显示耗时，不能视为完整语音输入的延迟承诺。** M5 的此前验证也不等于新版暂停功能的真机验收。

## 下载与安装

**0.2.1 一体安装包已构建**，包含完整 App、arm64 Python、推理依赖、通用 REAL-TSE 权重及经集成授权的官方 BlackHole 2ch。无需安装开发工具或单独下载模型、驱动。当前仍为 private 仓库中的 Draft 验收包；真实新设备验收、原生依赖最终复核及 Developer ID／公证尚待完成。

请阅读 [完整安装指南](BUNDLED_APP.md)。有权限的维护者从 [GitHub Releases](https://github.com/chenerzhong123-cloud/micforyou/releases) 的 `v0.2.1-local-alpha` Draft Assets 下载 `.pkg` 和 `.sha256`，核对后双击安装；公开发布后用户使用同样流程。安装前结束音频并退出旧版，App 安装到 `/Applications`，首次安装驱动后按提示重启。打开 App 注册声音；模型导出、校验与性能检查通过后，将豆包输入设备选为 `BlackHole 2ch`。安装器不删除个人数据。

目前仓库仍为私有，访问需要权限，暂无公开完整 Release 资产。GitHub 的 `Source code (zip)` 是源码，不是 App 安装包。开发者仍可使用 [源码安装指南](INSTALL.md)。

模型分开遵循各自的许可：Ke Zhang 自有部分获 Apache-2.0 授权，WeSpeaker ECAPA 预训练参数按上游 CC BY 4.0 保留署名。见 [模型声明](../licenses/MODEL_NOTICES.md) 和 [许可核查](MODEL_DISTRIBUTION_AUDIT.md)。

## 日常使用

首次设置完成后，打开 MicForYou 菜单，点击“开始过滤”，等待显示“正在过滤”，再用豆包语音输入。

| 操作 | 送往输入法的声音 | 麦克风 |
| --- | --- | --- |
| 开始过滤 | 处理后的音频；加载完成前静音 | 使用中 |
| 暂停过滤 | **原始声音继续输入，包括本人、旁人和环境声** | 仍在使用 |
| 继续过滤 | 重建流式状态后恢复过滤，不重开设备 | 仍在使用 |
| 结束 | 停止本链路的声音输出 | 释放 |
| 退出界面 | 后台音频继续，保持当前模式 | 运行或暂停时仍在使用 |

暂停的是过滤，不是收音。要关闭麦克风，请点击“结束”，再退出界面。更换麦克风或重新注册也必须先“结束”。暂停与继续不需要重新选择豆包输入设备。

偏好 Terminal 的用户可以在项目目录使用：

```bash
uv run micforyou status
uv run micforyou start
uv run micforyou pause   # 原音直通；麦克风继续工作
uv run micforyou resume  # 恢复过滤
uv run micforyou stop    # 结束并释放麦克风
```

MicForYou 不自动修改系统默认输入。如果豆包没有独立输入设备选择器，可手动在“系统设置 → 声音 → 输入”选择 BlackHole；结束后按需改回实体麦克风。系统输出继续使用原来的扬声器 / 耳机。

## 支持范围与已知限制

- 可减少部分他人声，**不能保证完全隔离**。本人不说话时，其他人的声音仍可能被识别。它不是身份验证或隐私隔离工具。
- 暂停原音直通已有自动检查和真实 ONNX + 合成输入验证；真实设备切换、豆包体验与新版 30 分钟稳定性验收仍待完成。详见 [本次验证记录](PAUSE_PASSTHROUGH_VALIDATION.md)。
- 源码仓库不提交权重或个人录音；完整 App 可按分开的 Apache-2.0 / CC BY 4.0 条款内置通用权重。详见 [许可核查](MODEL_DISTRIBUTION_AUDIT.md)。

## 本机数据与异常行为

MicForYou 的声音前处理与注册在本机进行；它不实现 ASR，也不输入文字。豆包的识别和数据处理遵循豆包自身规则，不能把“本机前处理”理解为整个语音输入流程离线。

默认运行故障时静音；主动暂停则明确转为原音直通。这两种情况有不同状态，不会将故障悄悄当成暂停。所选麦克风断开时不自动换成另一支麦克风。

配置和运行元数据保存在 `~/Library/Application Support/MicForYou/`，新运行报告放在其 `work/runs/` 下。日志不保存音频、embedding 或输入法文字。App 注册的录音与个人模型保存在 `~/Library/Application Support/MicForYou/registrations/`；源码安装可使用配置指定的其他目录。不要把个人数据提交到 GitHub。

## 更新、排查与卸载

完整包更新：先点击“结束”并退出界面，下载并运行新版完整 `.pkg`，再打开 `/Applications/MicForYou.app`。Application Support 中的声音和设置会保留；更新后先确认就绪，再开始过滤。
从 0.1.1 控制器升级时，需在完整 App 中重新注册一次；新注册通过后才替换配置。

源码安装用户再按以下命令更新。此命令生成控制器外壳，不生成完整运行包：

```bash
git pull --ff-only
uv sync --extra dev
./app/MicForYouMenuBar/install_app.sh
```

配置、模型和注册不会因此被删除。旧版本“暂停”实际上已停止收音；升级后不会自动打开麦克风，需重新点击“开始过滤”。不要在原音输出期间热替换运行文件。

- “需要完成设置”：在“设置”中检查驱动、麦克风和声音注册进度；源码用户也可运行 `uv run micforyou status`。
- “没有文字”：确认状态已就绪，豆包选中 `BlackHole 2ch`，并检查 macOS 对实际录音进程的麦克风授权。
- “麦克风还在使用”：暂停和退出界面都会保留音频，请先“结束”；也可运行 `uv run micforyou stop`。
- 卸载：先结束、退出，把 `/Applications/MicForYou.app`（以及旧 ZIP 留在 `~/Applications` 的副本）移入废纸篓，恢复豆包输入设备。配置、声音注册和 BlackHole 是单独的资源，按需备份和移除。

[完整包安装](BUNDLED_APP.md) · [源码安装](INSTALL.md) · [菜单栏操作](MENU_BAR_APP.md) · [性能检查](PERFORMANCE_GUIDE.md) · [研发记录](DEVELOPMENT_HISTORY.md) · [视频源码](../video/README.md)

## 项目许可与第三方组件

本项目自有代码与文档采用 [Apache-2.0](../LICENSE)，署名见 [NOTICE](../NOTICE)。该许可不替代模型、运行库与官方驱动的各自条款，详见 [模型声明](../licenses/MODEL_NOTICES.md)、[BlackHole 声明](../licenses/BLACKHOLE_NOTICES.md) 与 [原生运行库声明](../licenses/NATIVE_NOTICES.md)。

现有 0.2.1 安装包构建于 10 月 9 日。本次在 Draft Release 补充 LICENSE 和 NOTICE 附件，不改写既有安装包；后续完整构建会将两者放入 App，并在安装器中展示项目许可。
