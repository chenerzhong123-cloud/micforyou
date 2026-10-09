# 模型许可与完整 App 分发核查

更新：2026-10-09。对象为 REAL-TSE `tfmap_context_causal_100`。

**作者自有部分已获 Apache-2.0 书面授权；ECAPA 预训练参数被作者明确排除，按 WeSpeaker 官方 CC BY 4.0 声明处理。不能把整个 checkpoint 统一标为 Apache-2.0 或 MIT。**

## 作者回信

2026-10-09 17:44（Asia/Shanghai），Ke Zhang 从源文件中的公开联系地址回复此前的具体 checkpoint 询问。已通过 Gmail 读取正文，并核对来源账户、主题、checkpoint 名称和 SHA-256。原始回信只保存在本机忽略的 `outputs/licensing-inquiry/reply-20261009.json`；不把私人通信和邮件头提交仓库。

作者确认其本人编写的推理源码和本人训练的参数使用 Apache-2.0，许可商业终端应用、App 内置和 GitHub Releases 再分发、ONNX / Core ML 转换，以及修改或注册条件化变体。无需就这些用途再向他另行申请。分发应保留许可证、版权声明、改动标记和适用 NOTICE。

授权明确排除 WeSpeaker `voxceleb_ECAPA512.zip` 的预训练参数，包括保留或微调后的版本。作者不能代授第三方权利。作者希望 App 与项目页提供来源致谢，并说明这只是署名请求，不是额外许可条件，也不构成对产品的背书。

## 第三方参数与公开许可依据

| 对象 | 依据 | 本项目处理 |
| --- | --- | --- |
| REAL-TSE 自有推理源码和 TSE 参数 | 上述作者书面授权；部分源码亦有 Apache-2.0 SPDX | 保留 Apache-2.0 全文和源码版权头，标注离线加载器 / 导出改动 |
| WeSpeaker ECAPA 预训练参数 | [固定源码版本的官方预训练文档](https://github.com/wenet-e2e/wespeaker/blob/8f53b6485d9f88a207bd17e7f8dba899495ec794/docs/pretrained.md) 的 Model License 将 VoxCeleb 模型声明为 CC BY 4.0，模型列表指向 ECAPA512 | 保留 WeSpeaker / VoxCeleb 来源、模型链接、CC BY 4.0 全文、既有微调与转换说明，按此依据内置当前参数 |
| 同模型 Hugging Face 页面 | [官方 ECAPA512 页面](https://huggingface.co/Wespeaker/wespeaker-voxceleb-ecapa-tdnn512) 另标 Apache-2.0 | 记录声明差异；不借此移除明确覆盖预训练参数的 CC BY 署名 |
| WeSpeaker 源码 | [固定版本 LICENSE](https://github.com/wenet-e2e/wespeaker/blob/8f53b6485d9f88a207bd17e7f8dba899495ec794/LICENSE) 为 Apache-2.0 | 只内置所需 ECAPA / pooling 模块，保留版权头和改动标记 |
| Python 和 wheel / 原生运行库 | 各组件自己的 LICENSE / NOTICE | 运行包保留其声明；已识别 LGPL／MPL 源码随包提供；bundle-manifest.json 记录实际版本、源码 hash 和许可文件；公开发布前需复核全部实际原生依赖 |
| BlackHole | [GPL-3.0 / 另行集成授权说明](https://github.com/ExistentialAudio/BlackHole#can-i-integrate-blackhole-into-my-app) | 不打包驱动；引导用户从官方独立安装 |

CC BY 4.0 允许按其条款分享和改编，包括商业用途；署名、改动标记和不施加额外限制的要求见 [官方条款](https://creativecommons.org/licenses/by/4.0/legalcode.en)。此处依据的是 WeSpeaker 对其预训练模型的公开许可，不能只用数据集许可自行推导模型许可。许可不授予作者无权授予的其他权利。

此前核查中，模型仓库无根 LICENSE、checkpoint ZIP 无许可文件，评测仓库 MIT 不覆盖模型。该历史判断已经由此次书面授权及第三方公开许可证据补充，不再把当前所有参数写作“等待作者授权”。

## 固定分发对象

- REAL-TSE source: `2a540977a348fbaa92e623210505430e2cec608d`。
- WeSpeaker source: `8f53b6485d9f88a207bd17e7f8dba899495ec794`。
- `tfmap_context_causal_100/avg_model.pt` SHA-256: `97c01b79b0cf1a5b914a4a3bc1113c1864752ebdd320f528e77a53202447fef2`，278,268,439 bytes。
- App 只内置通用 checkpoint，不分发开发者声音、个人特征或个性化 ONNX。
- 面向用户的完整声明见 [MODEL_NOTICES](../licenses/MODEL_NOTICES.md)，同时放入 App。

## 当前实现与发布边界

0.2.0 已实现独立 arm64 Python / 推理运行包、bundle 资源发现、首次注册、自动导出 / correctness / 性能 / 配速延迟检查与取消设置。注册只有全部通过后才原子保存配置；失败或取消保留旧注册。离线加载器避免无用的训练 / ASR / VAD 初始化依赖，神经网络模块及通用权重保持原样。

本地完整包已构建。已加入 libsndfile／soxr／ml_dtypes（含 Eigen）源码、CPython 原生依赖声明与替换说明，详见 [原生运行库声明](../licenses/NATIVE_NOTICES.md)。它仍是 ad-hoc 签名的验收用 Alpha：全部实际原生依赖的最终分发复核、新设备首次授权录音、真实麦克风 / 输入法 30 分钟验收及 Developer ID / 公证未完成。当前构建机无签名身份。尚未创建公开完整 Release，不能把这些检查写为通过。

参见 [完整 App 差距](COMPLETE_APP_GAPS.md)、[中文首次使用](BUNDLED_APP.md) 和 [English installation](BUNDLED_APP.en.md)。
