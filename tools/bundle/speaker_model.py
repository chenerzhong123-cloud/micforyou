# Copyright (c) 2022 Hongji Wang (jijijiang77@gmail.com)
#               2024 Shuai Wang (wsstriving@gmail.com)
# SPDX-License-Identifier: Apache-2.0
# MicForYou modification, 2026-10-09: ECAPA-only factory, without unrelated
# eager training/ASR model imports. ECAPA neural implementation is unchanged.
from wespeaker.models import ecapa_tdnn


def get_speaker_model(model_name):
    if model_name != "ECAPA_TDNN_GLOB_c512":
        raise ValueError(f"Unsupported bundled speaker encoder: {model_name}")
    return ecapa_tdnn.ECAPA_TDNN_GLOB_c512
