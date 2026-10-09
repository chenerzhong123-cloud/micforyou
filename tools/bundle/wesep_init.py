# MicForYou modification, 2026-10-09: offline checkpoint-only loader.
# Replaces upstream eager CLI/VAD imports; neural modules remain unchanged.
from pathlib import Path
from types import SimpleNamespace
import random
import numpy as np
import torch
import yaml
torch.set_num_threads(1)


def load_model_local(model_dir):
    from wesep.models import get_model

    random.seed(42)
    np.random.seed(42)
    torch.manual_seed(42)
    root = Path(model_dir)
    config = yaml.safe_load((root / "config.yaml").read_text())
    if config["model"]["tse_model"] != "TSE_BSRNN_SPK":
        raise ValueError("This bundle only supports the verified REAL-TSE model")

    def disable_pretrained(value):
        if isinstance(value, dict):
            return {k: None if k == "pretrained" else disable_pretrained(v)
                    for k, v in value.items()}
        return value

    model = get_model("TSE_BSRNN_SPK")(
        disable_pretrained(config["model_args"]["tse_model"]))
    payload = torch.load(root / "avg_model.pt", map_location="cpu", weights_only=True)
    model.load_state_dict(payload["models"][0], strict=True)
    return SimpleNamespace(model=model.eval(),
                           resample_rate=config["dataset_args"].get("resample_rate", 16000))
