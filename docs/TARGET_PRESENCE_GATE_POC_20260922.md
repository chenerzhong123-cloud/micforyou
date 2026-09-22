# Target-presence auxiliary gate PoC（2026-09-22）

状态：`SOURCE PASS / PUBLIC SMOKE PASS / PRIVATE FALSE-ACCEPT FAIL / REJECTED`。

## 目的与边界

本实验不以 detector 替代 TSE。假设链路仍为实体麦克风 → REAL-TSE → BlackHole → 豆包，只额外用 enrollment-conditioned target-speaker detector 判断本人是否存在；只有可靠确认本人缺席时才把 TSE 输出静音。它不实现或调用 ASR，也不尝试分离重叠人声。

## 固定来源

- `tuya/nomo-pvad` release `1.1`，annotated tag 指向 commit `cb828468d183424fd574984f00b3ffbcce0be9bc`；
- detector 权重 `36,576,677 bytes`，SHA-256 `0acf2f3e75409b172771663fd1bee31af2760dba4e25b1353d2c26726b6412d1`；
- enrollment ERes2NetV2 权重 `71,768,231 bytes`，SHA-256 `0eb4057106b2573dd7b132cf0c36273ab29afd192c1610f80baa9c556dbb963c`；
- 上游声明代码、detector 权重及 ERes2NetV2 来源均为 Apache-2.0。项目未复制或提交这些模型文件。

上游公开示例能够运行，并呈现预期的前段 target / 后段 non-target 概率分离。首次环境安装还发现 `modelscope 1.40.1` 未声明实际需要的 `addict`；隔离环境补装 `addict 2.4.0` 后通过，未修改上游源码。

## 私有 held-out 结果

使用人工确认的 S03 enrollment，在 Q01/Q02/Q03 的 48 kHz 原音上运行上游实际 160 ms sliding-window wrapper。音频仅在本机读取，没有写出处理音频、embedding 或转写。详细 JSON 保存在 Git 外。

| case | 已知类别 | P(target) >= 0.5 | P(target) >= 0.7 | call p95 | RTF |
| --- | --- | ---: | ---: | ---: | ---: |
| Q01 | 本人在场 | 73.37% | 52.07% | 38.10 ms | 0.222 |
| Q02 | 本人缺席 | **90.24%** | **70.73%** | 41.52 ms | 0.219 |
| Q03 | 交替 | 74.52% | 61.15% | 57.60 ms | 0.250 |

Q02 的 median P(target) 为 `0.7952`，甚至高于 Q01 的 `0.7255`。这不是阈值或 hysteresis 可以修复的边界：提高阈值会同时删除更多本人声音，降低阈值则继续放行 Q02。运行成本在 Mac A 可接受，但质量 gate 已先失败，因此不生成试听文件、不接入 BlackHole/豆包，也不做实时稳定性测试。

## 判定

当前 `nomo-pvad release-1.1` 对本项目真实环境的 false accept 过高，候选淘汰。target-presence gate 作为架构扩展点仍保留，但只有新的 detector 在独立 Q01/Q02 上同时证明高 target recall 和低 target-absent false accept 才能重启。当前 Experimental Alpha 保持不变。

复现入口为 `experiments/probe_nomo_pvad.py`；它只输出概率、耗时、文件哈希和脱敏文件名，绝不写处理音频。
