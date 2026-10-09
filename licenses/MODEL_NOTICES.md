# MicForYou model credits and distribution notices

Target speaker extraction uses a model developed by Ke Zhang and released
through the [REAL-TSE WeSep project](https://github.com/REAL-TSE/wesep-real-tse).
This attribution does not imply endorsement of MicForYou.

## REAL-TSE inference code and TSE parameters

Source revision: 2a540977a348fbaa92e623210505430e2cec608d.
Checkpoint: tfmap_context_causal_100/avg_model.pt.
SHA-256: 97c01b79b0cf1a5b914a4a3bc1113c1864752ebdd320f528e77a53202447fef2.

Copyright (c) Ke Zhang and the respective upstream contributors.
Ke Zhang's inference source and parameters trained by him are licensed under
Apache License 2.0, as clarified in writing on 2026-10-09. That clarification
permits commercial use, app redistribution, ONNX/Core ML conversion and
modified/enrollment-conditioned variants. It excludes third-party pretrained
parameters. See Apache-2.0.txt; existing source copyright headers are retained.
The TSE portion was trained on Libri2Mix train-100. No training audio is included.

## WeSpeaker ECAPA-TDNN parameters and code

The checkpoint includes retained/fine-tuned parameters derived from WeSpeaker's
voxceleb_ECAPA512.zip. These are outside Ke Zhang's Apache grant.
The [WeSpeaker pretrained-model documentation](https://github.com/wenet-e2e/wespeaker/blob/8f53b6485d9f88a207bd17e7f8dba899495ec794/docs/pretrained.md)
identifies VoxCeleb pretrained models as CC BY 4.0. We retain this attribution
and the full CC BY 4.0 legal code (CC-BY-4.0.html).

Model provider: WeSpeaker contributors. Dataset creators: Arsha Nagrani,
Joon Son Chung and Andrew Zisserman (VoxCeleb).
Original model: https://wespeaker-1256283475.cos.ap-shanghai.myqcloud.com/models/voxceleb/voxceleb_ECAPA512.zip
Dataset: https://mm.kaist.ac.kr/datasets/voxceleb/
License: https://creativecommons.org/licenses/by/4.0/

The model's Hugging Face page separately declares Apache-2.0:
https://huggingface.co/Wespeaker/wespeaker-voxceleb-ecapa-tdnn512
We do not use this alternate declaration to remove CC BY attribution.
Upstream retained/fine-tuned these parameters for REAL-TSE; MicForYou uses them
for local enrollment conditioning, and converts the TSE core to ONNX. Converted
or conditioned models retain these origin and modification notices.

WeSpeaker source revision: 8f53b6485d9f88a207bd17e7f8dba899495ec794.
Source code license: Apache-2.0. Copyright headers in ECAPA and pooling code
are retained. Full license: Apache-2.0.txt.

## MicForYou changes (2026-10-09)

- An offline checkpoint loader replaces WeSep CLI/VAD imports; the neural
  implementations and checkpoint remain unchanged.
- WeSpeaker's package initializer and model factory are reduced to the verified
  ECAPA implementation; unrelated training/ASR imports are omitted.
- Stateful TSE export exposes recurrent state and represents complex tensors
  as real/imaginary inputs. User conditioning is computed locally.

The App contains only the general checkpoint. It does not include a developer's
voice recording, enrollment features, personalized ONNX model or training data.

## Runtime dependencies

Python LICENSE/third-party notices and Python wheel license files remain in
Runtime/python. Runtime/bundle-manifest.json lists exact installed packages
and license-file locations. These components have their own licenses; the
model's Apache-2.0 grant does not relicense them.
Identified LGPL/MPL source archives, CPython native notices, and replacement
instructions are included; see NATIVE_NOTICES.md. A final review of all actual
native binaries remains pending before public distribution. It is not marked
release-ready.
BlackHole is not bundled. Users install it from its official distributor.
