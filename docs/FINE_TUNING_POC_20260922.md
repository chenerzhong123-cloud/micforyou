# 个性化微调 PoC（2026-09-22）

状态：`4-STEP REAL-OFFICE REJECTED / 40-STEP REJECTED / CURRENT ALPHA UNCHANGED`。

## 数据边界

- 本人训练数据：第一批 Mac B enrollment、normal、quiet。
- 独立验证数据：第二批 Mac B enrollment、normal、quiet。
- 干扰数据：OpenSLR SLR12 `dev-clean`，官方压缩包 MD5 `42e2234ba48799c1f50f24a7926300a1`，随包许可证为 CC BY 4.0。
- 训练干扰说话人：8 人；验证干扰说话人：另外 4 人，speaker ID 不重叠。
- Q01–Q03 真实办公室音频完全未参与训练，仍为 held-out。
- 可辨认同事语音未用于训练。

## 训练范围

当前 REAL-TSE 共 `27,242,122` 个参数。PoC 冻结 speaker frontend、separator 和 mask 主体，只更新每个频带 mask 的最终 projection，共 `527,364` 个参数（约 1.9%）。训练加入相对原始参数的 proximity 项；所有输出写入独立本地目录，源 checkpoint SHA-256 `97c01b79...47fef2` 在实验前后保持不变。

## 4-step 候选

使用 3 秒 crop、MPS、学习率 `1e-6`：

| 独立 Mac B 验证 | 原模型 | 4-step |
| --- | ---: | ---: |
| 平均 SI-SDRi | 8.53 dB | 9.26 dB |
| 目标缺席平均衰减 | -22.54 dB | -23.13 dB |
| 最差本人单项变化 | — | -0.43 dB |

候选已用 Mac A 当前 6 秒 enrollment 导出独立 ONNX；Torch/ONNX 100 chunks 数值一致性 PASS。75 秒真实办公室处理 RTF `0.342`，model-call p95 `22.58 ms`，与当前实时预算兼容。

但真实办公室的 RMS 显示明显更强的整体抑制：

| Held-out | 当前基线 | 4-step 候选 |
| --- | ---: | ---: |
| Q01 本人出现 | -1.82 dB | -5.88 dB |
| Q02 本人缺席 | -2.43 dB | -4.74 dB |
| Q03 交替说话 | -1.83 dB | -4.17 dB |

Q02 的 RMS 方向看似正确，但 Q01 也额外降低约 4.1 dB，因此进行了人工审听。用户确认 Q01 中本人的声音也被去掉一部分；Q02 只有略微减少，效果不明显、近似相同。说明额外衰减主要不是有效的身份选择性改善。4-step 候选因此违反“本人完整”硬门槛并被拒绝，不进入豆包或实时验收。

## 40-step 候选

相同 3 秒设置扩展到 40 steps 后，独立验证反而退化：平均 SI-SDRi `8.53 → 8.36 dB`，目标缺席衰减 `-22.54 → -21.93 dB`，且一条 quiet 样本约下降 `1.70 dB`。该模型已拒绝，不导出、不部署。结果说明当前小数据设置很快过训练，不能通过增加 steps 解决。

## 当前判定

本轮“只训练最终 mask projection + 当前小数据/loss”路线已经关闭：4-step 在真实办公室伤害本人而未明显降低他人，40-step 在独立受控验证也退化。继续增加 steps 或在同一验证集上调参会扩大过拟合，不再进行。当前 Experimental Alpha 保持不变。

后续若重启训练，必须有实质变化，例如更丰富的本人跨设备/房间语音、多个知情干扰说话人、显式 target-presence/identity loss，或解冻不同模块并使用新的独立验证集；不能把当前数据重复调参包装成进展。优先级重新回到更强、可审计的 causal waveform TSE 模型 source gate。
