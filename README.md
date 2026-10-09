# MicForYou

[English](README.en.md) · 简体中文

<img src="app/MicForYouMenuBar/Resources/AppIcon.png" width="96" alt="MicForYou 正式 Logo">

**空间共享，表达从容。**

在开放工位里口述方案，身旁的交谈不必都挤进你的句子。MicForYou 以你的注册声音为参考，在 Mac 本机处理麦克风音频，减少部分附近人声和环境干扰，再交给你熟悉的豆包输入法识别文字。

这是面向愿意动手配置的 Mac 用户的 **Experimental Alpha**。计划通过 GitHub 分发，当前没有 App Store 版本。**当前应用是菜单栏控制器，仍需要本地 Python 运行环境、模型、声音注册和 BlackHole 2ch；下载 `.app` 并不等于完成全部安装。**

## 看看它如何工作

[![MicForYou 最新宣传片预览](docs/media/promo-preview.png)](docs/media/micforyou-promo-latest.mp4)

[观看 / 下载最新宣传片（MP4，55 秒）](docs/media/micforyou-promo-latest.mp4)。点击后可在 GitHub 文件页下载播放。画面、转写和波形是动画演示，不是实测效果对比。

## 硬件与性能要求

**当前推荐以已验证的 MacBook Air M5 为运行基线。已测试的 M1 未达到当前模型的实时要求，不推荐用于过滤。** 其他设备即使芯片更新或规格更高，也需要先通过本机性能检查；目前不能仅凭型号保证延迟可接受。

| 项目 / 设备 | 当前要求与验证结果 |
| --- | --- |
| 系统与架构 | 菜单栏界面要求 **macOS 14+**；当前构建为 **Apple Silicon（arm64）**，Intel 未验证。 |
| MacBook Air M5 | 此前通过 [30 分钟运行验证](docs/MAC_A_NEXT_STAGE.md)，bridge 内部音频延迟 p95 约 **260 ms**。这是当前已验证基线，实际表现仍受负载和电源状态影响。 |
| MacBook Pro M1（已测试设备） | 当前 REAL-TSE checkpoint 的最佳有效 RTF 为 **1.052**，处理速度低于实时要求，不能持续跟上音频输入。当前不支持该设备上的实时过滤。 |
| 其他 Mac | 尚无足够验证，包括其他代际和 Pro / Max / Ultra 型号。具备相当或更强持续处理能力的设备可以作为候选，但不能跳过性能检查。 |

安装时须完成 [安装指南第 5 节的本机性能检查](docs/INSTALL.md)：推荐候选的 **RTF ≤ 0.80**（处理耗时 / 音频时长，保留至少 20% 吞吐余量），配速复核的 **bridge 内部延迟 p95 < 400 ms**，且无 FAULT 或持续音频欠载（underrun）。建议接通电源，并在日常工作负载下复核；后台重负载可能让同一台机器从达标变为不达标。详见 [性能指南](docs/PERFORMANCE_GUIDE.md) 和 [M1 测试记录](docs/MAC_B_COREML_THREAD_RECHECK_RESULTS_20260918.md)。

**上述延迟是 MicForYou 音频链路的指标，不包含豆包识别及文字显示耗时，不能视为完整语音输入的延迟承诺。** M5 的此前验证也不等于新版暂停功能的真机验收。

## 下载与安装

推荐先阅读 [完整安装指南](docs/INSTALL.md)，按顺序完成：

1. 下载仓库源码，安装 `uv` 和 Apple Command Line Tools。
2. 安装 BlackHole 2ch 并重启 Mac。它是语音输入需要的音频路由组件。
3. 在独立 Python 环境中准备 REAL-TSE 源码与用户自行取得的权重。
4. 用日常麦克风注册自己的声音，在本地导出并校验个性化 ONNX，完成配置。
5. 构建菜单栏 App，安装到 `~/Applications`，将豆包输入设备选为 `BlackHole 2ch`。

仓库地址：[chenerzhong123-cloud/micforyou](https://github.com/chenerzhong123-cloud/micforyou)。目前仓库仍为私有，**尚无已发布 Release 或公开下载包**；访问者需要仓库权限。拿到访问权限后可以：

```bash
git clone https://github.com/chenerzhong123-cloud/micforyou.git
cd micforyou
uv sync --extra dev
```

也可以在 GitHub 的 **Code → Download ZIP** 下载源码，解压后进入目录。源码 ZIP 不包含 Python 环境、权重和声音注册。源码目录安装后要保留，App 会从配置记录的该目录调用控制程序。

未来提供预构建包时，请从 [GitHub Releases](https://github.com/chenerzhong123-cloud/micforyou/releases) 的 **Assets** 下载 `.app.zip`，不要将 GitHub 自动生成的 `Source code (zip)` 当成安装包。菜单栏包仍需先完成运行环境设置。当前构建为 ad-hoc 签名，未做 Developer ID 签名与公证；首次打开被拦截时，按 [Apple 的说明](https://support.apple.com/en-us/102445)，在“系统设置 → 隐私与安全性”中对确认来源的应用选择“仍要打开”。

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
- 暂停原音直通已有自动检查和真实 ONNX + 合成输入验证；真实设备切换、豆包体验与新版 30 分钟稳定性验收仍待完成。详见 [本次验证记录](docs/PAUSE_PASSTHROUGH_VALIDATION.md)。
- 模型权重不会随源码或菜单栏安装包分发。现有 REAL-TSE 权重的统一分发许可尚不明确，用户需自行从上游取得并遵循其条件；参见 [模型来源与许可记录](docs/STAGE_B.md#license-boundary)。

## 本机数据与异常行为

MicForYou 的声音前处理与注册在本机进行；它不实现 ASR，也不输入文字。豆包的识别和数据处理遵循豆包自身规则，不能把“本机前处理”理解为整个语音输入流程离线。

默认运行故障时静音；主动暂停则明确转为原音直通。这两种情况有不同状态，不会将故障悄悄当成暂停。所选麦克风断开时不自动换成另一支麦克风。

配置和运行元数据保存在 `~/Library/Application Support/MicForYou/`，新运行报告放在其 `work/runs/` 下。日志不保存音频、embedding 或输入法文字。注册音频与个性化 ONNX 保存在你选择的本机目录，不要提交到 GitHub。

## 更新、排查与卸载

更新前先点击“结束”，退出菜单栏界面，再更新源码及控制环境：

```bash
git pull --ff-only
uv sync --extra dev
./app/MicForYouMenuBar/install_app.sh
```

配置、模型和注册不会因此被删除。旧版本“暂停”实际上已停止收音；升级后不会自动打开麦克风，需重新点击“开始过滤”。不要在原音输出期间热替换运行文件。

- “需要完成设置”：运行 `uv run micforyou status`，检查缺失路径和设备名。
- “没有文字”：确认状态已就绪，豆包选中 `BlackHole 2ch`，并检查 macOS 对实际录音进程的麦克风授权。
- “麦克风还在使用”：暂停和退出界面都会保留音频，请先“结束”；也可运行 `uv run micforyou stop`。
- 卸载：先结束、退出，把 `~/Applications/MicForYou.app` 移入废纸篓，恢复豆包输入设备。配置、声音注册和 BlackHole 是单独的资源，按需备份和移除。

[完整安装](docs/INSTALL.md) · [菜单栏操作](docs/MENU_BAR_APP.md) · [性能检查](docs/PERFORMANCE_GUIDE.md) · [研发记录](docs/DEVELOPMENT_HISTORY.md) · [视频源码](video/README.md)
