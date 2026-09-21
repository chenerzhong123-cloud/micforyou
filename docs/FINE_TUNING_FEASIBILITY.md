# 当前 REAL-TSE 微调可行性

日期：2026-09-22。结论：`BOUNDED MPS STEP PASS / DATA AND QUALITY EXPERIMENT NOT STARTED`。

当前 checkpoint 已在 Mac A 上通过实时链路和设备恢复验收，用户也确认真实办公室样本比原音更好，能减少部分他人声和噪音。但目标缺席片段仍可被豆包完整转写。微调可以作为后续研究方向，不能把现有证据解释为只差一次简单训练。

## 已核实事实

- `tfmap_context_causal_100` 为 `TSE_BSRNN_SPK`，共 `27,242,122` 个参数：分离器约 `18.87M`，speaker frontend 约 `8.37M`。
- 本地 checkpoint 文件约 `278 MB`，其中还包含 optimizer、scheduler 和 scaler 状态；它不是仅含推理权重的小文件。
- 官方配置是 150 epochs、batch size 12、六层 causal BSRNN、16 kHz，并以 LibriSpeech/LibriMix 规模的数据组织方式训练。
- 当前官方训练入口直接调用 `torch.cuda.set_device`、NCCL、`.cuda()` 和 DistributedDataParallel。它不能原样在 Mac A 的 MPS 或 CPU 上运行。
- 两批 Mac B 录音的 SHA-256 均不同，确为两套独立采集。每套包含 60 秒 enrollment、25 秒正常说话和 25 秒轻声说话，可严格拆分训练和验收，但本人独立测试语音合计仍只有约 100 秒。
- 真实办公室录音中已有本人和他人片段，可用于诊断；当前没有把同事语音从“效果验收材料”扩大为“模型训练材料”的授权。
- Mac A M5 已用确定性合成张量完成一次受限 MPS forward、backward 和 optimizer step：只解冻各频带 mask 的最终 projection，共 `527,364` 个可训练参数；梯度均为有限值，未保存 checkpoint。该结果只证明训练技术路径可运行，不证明真实数据收敛或质量改善。

## 为什么现在不直接训练

1. **训练程序要先改造。** 官方入口仍需新增单进程 CPU/MPS 路径、真实 loss/data loader、可恢复 checkpoint 和确定性评估。最小 MPS backward 已通过，但这不是完整 trainer。
2. **数据不足且分布窄。** 约 100 秒本人测试语音容易使 2724 万参数模型记住设备、房间和句子，离线分数变好也可能只是过拟合。
3. **失败点是“同事被当成本人”。** 只用本人干净录音和公开干扰音训练，未必能修复真实办公室中的相似声线、距离、混响和设备响应。
4. **不能污染验收集。** 已用于证明目标缺席失败的片段必须保留为 held-out，不可再拿同一片段训练后宣称问题已解决。
5. **数据使用边界不同。** 本地试听和质量判断不等于允许用可辨认的同事声音训练模型。若要使用，必须先由用户确认录音来源与相关人员的知情/许可；否则只用公开许可干扰音或新录制的知情协作样本。

## 推荐执行顺序

### 1. 冻结当前 Experimental Alpha

保持现有 ONNX、6 秒 enrollment、实时参数和故障恢复不变。它可继续用于 Mac A 试用和收集主观问题，但界面和文档继续显示“部分过滤，不是隐私隔离”。任何质量实验都使用新的模型 ID 和输出目录，不能覆盖已通过的运行基线。

### 2. 先做新模型 source gate

只接纳同时满足以下条件的候选：

- 以音频 enrollment 指定目标说话人；
- waveform 输出，可送入豆包；
- causal/streaming 或能证明有界 lookahead；
- 权重真实可下载且许可可审计；
- 能在 Mac A 免费、本地运行；
- 先过现有独立 0/-6/-12 dB、目标缺席和真实办公室 held-out 测试，再进入实时链路。

截至 2026-09-22，官方 REAL-TSE Challenge 仍主要提供已经测试过的四个 BSRNN 变体；新版 WeSep 自身把官方 pretrained packages、CLI inference 和部署列为尚在验证/待发布。因此目前没有一个已经确认可直接替换的官方轻量 checkpoint。论文中的更轻架构只有在权重、许可和真实 streaming 实现都可取得时才进入工程评估。

### 3. 只有 source gate 无结果时，做受限微调 PoC

建议不是全量训练，而是：

- 冻结 speaker frontend 和大部分 separator；
- 只解冻最后的 mask/少量 BSRNN 层，先把可训练参数压到可控范围；
- 用 Mac B 第一套独立语音训练，第二套只做 held-out；
- 干扰端优先使用公开许可数据；只有取得明确许可后才加入真实办公室他人语音；
- target-absent 必须进入 loss/采样策略，不能只优化 target-present SI-SDR；
- 每轮同时比较当前 checkpoint，防止以压低全部输出换取“过滤变强”。

PoC 的继续门槛：held-out 本人语义不明显退化，目标缺席泄漏显著下降，0/-6 dB 不倒退，并且导出后的 Mac A p95 仍不超过 500 ms。任何一项失败就停止扩大训练。

能力 smoke 可用 `experiments/probe_finetune_mps.py` 复现。它只在内存里更新一次最终 mask projection，使用合成张量，不读取项目语音、不保存模型，不能当作微调结果。

## 需要用户决定的唯一数据问题

开始训练前必须决定：是否允许把真实办公室录音中可辨认的同事声音仅在本机用于模型训练。选择“不允许”不会阻塞项目；我们仍可使用公开许可干扰音和以后由知情参与者专门录制的材料，只是对真实办公室误放行的修复把握会更低。

## 来源

- WeSep 当前状态与发布边界：<https://github.com/wenet-e2e/wesep>
- REAL-TSE Challenge checkpoint 与评估：<https://github.com/REAL-TSE/REAL-TSE-Challenge>
- 本项目已有轻量候选筛选：[`LIGHTWEIGHT_TSE_SCREENING_20260918.md`](LIGHTWEIGHT_TSE_SCREENING_20260918.md)
