"""Branch A: default dynamic INT8 quantization of the FP32 TSE core.

Emits the FP32 operator histogram first (no assumptions about dominant ops),
runs onnxruntime.quantization.quantize_dynamic() once with defaults, then
reports sizes, both histograms, and the operators actually quantized.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import onnx
from onnxruntime.quantization import quantize_dynamic, QuantType


def histogram(path: Path) -> dict[str, int]:
    model = onnx.load(str(path))
    return dict(sorted(Counter(node.op_type for node in model.graph.node).items()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fp32", type=Path, required=True)
    parser.add_argument("--int8", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    fp32_hist = histogram(args.fp32)
    print("FP32 operator histogram:")
    for op, count in sorted(fp32_hist.items(), key=lambda kv: -kv[1]):
        print(f"  {op}: {count}")

    quantize_dynamic(
        model_input=str(args.fp32),
        model_output=str(args.int8),
        weight_type=QuantType.QInt8,
    )

    int8_hist = histogram(args.int8)
    quantized_ops = {
        op: count - fp32_hist.get(op, 0)
        for op, count in int8_hist.items()
        if count > fp32_hist.get(op, 0)
    }
    removed_ops = {
        op: count - int8_hist.get(op, 0)
        for op, count in fp32_hist.items()
        if count > int8_hist.get(op, 0)
    }
    print("INT8 size:", args.int8.stat().st_size, "vs FP32:", args.fp32.stat().st_size)
    print("quantization-introduced ops:", quantized_ops)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": "micforyou/onnx-int8-quantize/1",
        "fp32_path": args.fp32.name,
        "fp32_size_bytes": args.fp32.stat().st_size,
        "fp32_sha256": __import__("hashlib").sha256(args.fp32.read_bytes()).hexdigest(),
        "int8_path": args.int8.name,
        "int8_size_bytes": args.int8.stat().st_size,
        "weight_type": "QInt8",
        "method": "quantize_dynamic (defaults)",
        "fp32_operator_histogram": fp32_hist,
        "int8_operator_histogram": int8_hist,
        "quantization_added_ops": quantized_ops,
        "quantization_removed_ops": removed_ops,
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"report: {args.report}")


if __name__ == "__main__":
    main()
