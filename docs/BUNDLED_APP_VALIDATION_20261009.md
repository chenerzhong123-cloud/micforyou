# 0.2.0 完整 App 本地验证

日期：2026-10-09。构建机：MacBook Air M5（Mac17,3），macOS arm64。
对象：`MicForYou-0.2.0-local-alpha-macos-arm64.app.zip`。

**完整运行包与离线首次设置流水线已通过本机验证。当前仍是本地 Alpha，未完成新设备麦克风权限、真实录音／输入法或公开发布验收。**

## 已验证

| 检查 | 结果与范围 |
| --- | --- |
| 控制器自动测试 | 98 passed；分别在开发环境和独立 CPython 3.12.13／NumPy 1.26.4 环境运行，覆盖取消、失败不覆盖旧注册、全部延迟候选失败、自动增加 prefill 重试及旧控制器升级门槛 |
| Swift | release build、ModelCheck、BundleCheck、StandaloneCheck 通过；C01 正式图标 16–1024 px 可解码 |
| 首次启动／迁移 | App 移至带空格目录，以 Swift Process 调用实际内置 Python，在全新配置路径取得 STOPPED／未配置及 IDLE；无需项目 venv |
| 原始模型 | 严格加载通用 checkpoint；SHA-256 与作者确认对象一致，未替换神经网络实现 |
| 真实模型导出／数值一致性 | 内置 Python／离线源码导出 ONNX 85,313,823 bytes、7,445 nodes；100 chunk 校验 PASS，输出 max_abs 1.609e-6，h 2.183e-6，c 1.068e-4；阈值 1e-3 |
| 音频依赖 | 去除可选编码器的 libsndfile 1.2.0 与原 wheel 解码同一 WAV，SoundFile／Torchaudio 的 float32 数据 hash 完全一致 |
| 原生依赖路径 | 179 个 arm64 Mach-O 的加载依赖无开发机／Homebrew 绝对路径；无高于 macOS 14 的 LC_BUILD_VERSION 最低版本声明。此项不是 macOS 14 实机验证 |
| 完整设置流水线 | 用既有本机 WAV 替代录音，设备列表为测试替身；实际执行 export、100 chunk compare、benchmark、30 秒配速延迟检查，最终 READY 并原子保存个人模型配置 |
| 隐私／资源 | App 不包含开发者录音、个人 ONNX、Python 字节码缓存或 Windows DLL；依赖中无用的 ONNX／WAV 测试样本已去除；个人验证输出在 ignored outputs 中 |
| 签名 | 嵌套原生文件逐个 ad-hoc 签名；运行后及资源精简后的 `codesign --verify --deep --strict` 通过；ZIP 解压后再次核验。没有 Developer ID／公证 |

## 完整设置流水线性能

CPUExecutionProvider，intra-op threads = 1，10 秒合成音频。

| frames / chunk | processing RTF | 模型调用 p95 |
| --- | --- | --- |
| 8 | 0.349 | 22.6 ms |
| 16 | 0.243 | 31.0 ms |
| 24 | 0.216 | 41.4 ms |

自动选择 8 frames、prefill 100 ms；30 秒 wall-clock 配速复核：

- COMPLETED；输入／输出样本数一致，nonfinite = 0，underrun = 0。
- bridge 内部延迟 p95 **251.8 ms**，最大 **335.1 ms**。
- model_compute_rtf **0.410**。

配速测试采用实际 ONNX stream／BridgeEngine，在 Python 工作线程中处理合成输入。
没有打开 CoreAudio 设备；不包括实体麦克风、BlackHole、豆包识别及文字显示耗时。
它证明本机离线设置门槛可以通过，不能代替实际语音输入体验或 30 分钟稳定性验收。

## 本机验证资料与复现

完整日志、correctness／benchmark／latency JSON 和个人候选模型位于
`outputs/bundle-verification/`，被 Git 忽略。不得将其中真实注册录音或个性化模型随 App 分发。
在内置 Python 下运行开发者测试时需设置 `PYTHONDONTWRITEBYTECODE=1`，
使测试启动的子进程也不向 App 写缓存。产品的 Swift／bootstrap 启动路径已设置该环境。

`tools/bundle/verify_setup.py` 可以由完整 App 的 Python 执行，参数为
`--app`、本机 `--enrollment` WAV、新的 ignored `--work` 目录、唯一 `--token`
及 `--mode setup-worker`。该工具只替代设备发现与录音，不修改已有注册。
完整构建步骤见 [RELEASE](RELEASE.md)，使用全新输出目录。

## 未完成的验收

- 无开发环境新 Mac 上的 GUI、首次权限授权、真实 45 秒录音和个人模型生成。
- 实体麦克风／豆包 30 分钟混合运行，暂停原音、继续、结束、断链和升级。
- 全部实际原生依赖的最终分发复核；已识别 LGPL／MPL 源码和声明随包提供。
- Developer ID 身份和 Apple 公证；本机 `security find-identity -v -p codesigning` 为 0 个有效身份。
- 项目自身分发许可与公开访问方式；GitHub 仓库仍为 private，完整资产仅供 Draft Release 验收。

未自动安装或替换用户当前的 0.1.1 App。当前推荐基线仍为已验证 M5；
不能将本次 M5 合成输入结果外推为 M1 或其他未经验证设备支持。
