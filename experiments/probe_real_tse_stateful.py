"""Probe REAL-TSE's causal BSRNN with explicit recurrent state.

This does not claim waveform streaming yet. It computes the upstream centered
STFT once, then verifies that processing its time frames in bounded chunks with
LSTM state matches whole-utterance causal inference. The next step is a
streaming STFT/overlap-add wrapper with the same frame contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torchaudio


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def synchronize(device: torch.device) -> None:
    if device.type == "mps":
        torch.mps.synchronize()


def load_audio(path: Path, sample_rate: int) -> torch.Tensor:
    audio, source_rate = torchaudio.load(path)
    if audio.shape[0] > 1:
        audio = audio.mean(dim=0, keepdim=True)
    if source_rate != sample_rate:
        audio = torchaudio.functional.resample(audio, source_rate, sample_rate)
    return audio.float()


class StreamingSTFT:
    """Bounded centered-STFT frontend with PyTorch-compatible reflect edges."""

    def __init__(self, window_size: int, hop: int, device: torch.device):
        self.window_size = window_size
        self.hop = hop
        self.pad = window_size // 2
        self.window = torch.hann_window(window_size, device=device)
        self.buffer = torch.empty(1, 0, device=device)
        self.startup = torch.empty(1, 0, device=device)
        self.tail = torch.empty(1, 0, device=device)
        self.started = False
        self.frame_count = 0

    def _extract(self) -> list[torch.Tensor]:
        frames = []
        while self.buffer.shape[-1] >= self.window_size:
            windowed = self.buffer[..., : self.window_size] * self.window
            frames.append(torch.fft.rfft(windowed, n=self.window_size).unsqueeze(-1))
            self.buffer = self.buffer[..., self.hop :]
            self.frame_count += 1
        return frames

    def push(self, samples: torch.Tensor) -> list[torch.Tensor]:
        samples = samples.reshape(1, -1)
        self.tail = torch.cat([self.tail, samples], dim=-1)[..., -(self.pad + 1) :]
        if not self.started:
            self.startup = torch.cat([self.startup, samples], dim=-1)
            if self.startup.shape[-1] <= self.pad:
                return []
            left = self.startup[..., 1 : self.pad + 1].flip(-1)
            self.buffer = torch.cat([left, self.startup], dim=-1)
            self.startup = torch.empty(1, 0, device=samples.device)
            self.started = True
        else:
            self.buffer = torch.cat([self.buffer, samples], dim=-1)
        return self._extract()

    def flush(self) -> list[torch.Tensor]:
        if not self.started:
            raise ValueError("stream must contain more than window_size / 2 samples")
        right = self.tail[..., :-1].flip(-1)
        self.buffer = torch.cat([self.buffer, right], dim=-1)
        return self._extract()


class StreamingOLA:
    """Bounded overlap-add synthesis for centered STFT frames."""

    def __init__(self, window_size: int, hop: int, device: torch.device):
        self.window_size = window_size
        self.hop = hop
        self.pad = window_size // 2
        self.window = torch.hann_window(window_size, device=device)
        self.accumulator: torch.Tensor | None = None
        self.denominator = torch.zeros(window_size, device=device)
        self.padded_position = 0
        self.frame_count = 0

    def _take(self, count: int) -> torch.Tensor:
        assert self.accumulator is not None
        normalized = self.accumulator[..., :count] / self.denominator[:count].clamp_min(
            1e-11
        )
        start = max(0, self.pad - self.padded_position)
        emitted = normalized[..., start:count]
        self.accumulator = torch.cat(
            [
                self.accumulator[..., count:],
                torch.zeros(*self.accumulator.shape[:-1], count, device=normalized.device),
            ],
            dim=-1,
        )
        self.denominator = torch.cat(
            [
                self.denominator[count:],
                torch.zeros(count, device=normalized.device),
            ]
        )
        self.padded_position += count
        return emitted

    def push(self, spec: torch.Tensor) -> list[torch.Tensor]:
        outputs = []
        for index in range(spec.shape[-1]):
            time_frame = torch.fft.irfft(
                spec[..., index], n=self.window_size, dim=-1
            ) * self.window
            if self.accumulator is None:
                self.accumulator = torch.zeros_like(time_frame)
            self.accumulator += time_frame
            self.denominator += self.window.square()
            outputs.append(self._take(self.hop))
            self.frame_count += 1
        return [output for output in outputs if output.shape[-1]]

    def flush(self) -> list[torch.Tensor]:
        if self.accumulator is None:
            return []
        padded_length = (self.frame_count - 1) * self.hop + self.window_size
        valid_end = padded_length - self.pad
        outputs = []
        while self.padded_position < valid_end:
            outputs.append(self._take(min(self.hop, valid_end - self.padded_position)))
        return [output for output in outputs if output.shape[-1]]


def recurrent_chunk(block, value, state):
    normalized = block.norm(value).transpose(1, 2).contiguous()
    recurrent, new_state = block.rnn(normalized, state)
    projected = block.proj(recurrent.reshape(-1, recurrent.shape[2])).view(
        value.shape[0], value.shape[2], value.shape[1]
    )
    return value + projected.transpose(1, 2).contiguous(), new_state


def separator_chunk(separator, value, states):
    batch = value.shape[0]
    frames = value.shape[-1]
    value = value.view(batch, separator.nband * separator.feature_dim, frames)
    new_states = []
    for index, layer in enumerate(separator.separation):
        band_input = value.view(
            batch * separator.nband, separator.feature_dim, frames
        )
        band_output, state = recurrent_chunk(layer.band_rnn, band_input, states[index])
        band_output = band_output.view(
            batch, separator.nband, separator.feature_dim, frames
        )

        frequency_input = (
            band_output.permute(0, 3, 2, 1)
            .contiguous()
            .view(batch * frames, separator.feature_dim, separator.nband)
        )
        frequency_output = layer.band_comm(frequency_input)
        value = (
            frequency_output.view(
                batch, frames, separator.feature_dim, separator.nband
            )
            .permute(0, 3, 2, 1)
            .contiguous()
            .view(batch, separator.nband * separator.feature_dim, frames)
        )
        new_states.append(state)
    return value.view(batch, separator.nband, separator.feature_dim, frames), new_states


def precompute_conditioning(model, enrollment):
    conditioning = {}
    features = model.spk_configs["features"]
    if features["tfmap"]["enabled"]:
        conditioning["tfmap"] = model.sep_model.stft(enrollment)[0]
    if features["context"]["enabled"]:
        conditioning["context"] = model.spk_ft.context.compute(enrollment)
    if features["spkemb"]["enabled"]:
        conditioning["spkemb"] = (
            model.spk_ft.spkemb.compute(enrollment).unsqueeze(1).unsqueeze(3)
        )
    return conditioning


def condition_features(model, spec, conditioning):
    spec_ri = torch.stack([spec.real, spec.imag], dim=1)
    features_config = model.spk_configs["features"]
    if features_config["tfmap"]["enabled"]:
        tfmap = model.spk_ft.tfmap.compute(conditioning["tfmap"], torch.abs(spec))
        spec_ri = model.spk_ft.tfmap.post(spec_ri, tfmap.unsqueeze(1))
    subbands = model.sep_model.band_split(spec_ri)
    mixture_subbands = model.sep_model.band_split(spec)
    features = model.sep_model.subband_norm(subbands)
    if features_config["context"]["enabled"]:
        features = model.spk_ft.context.post(features, conditioning["context"])
    if features_config["spkemb"]["enabled"]:
        features = model.spk_ft.spkemb.post(features, conditioning["spkemb"])
    return features, mixture_subbands


def prepare_features(model, mixture, enrollment):
    mixture = mixture.squeeze(1)
    enrollment = enrollment.squeeze(1)
    spec = model.sep_model.stft(mixture)[-1]
    conditioning = precompute_conditioning(model, enrollment)
    features, mixture_subbands = condition_features(model, spec, conditioning)
    return features, mixture_subbands, conditioning, spec


def mask_frames(model, separated, mixture_subbands):
    estimated_ri = model.sep_model.band_masker(separated, mixture_subbands)
    return torch.complex(estimated_ri[:, 0], estimated_ri[:, 1])


def streaming_overlap_add(spec: torch.Tensor, window_size: int, hop: int):
    """Reconstruct centered-STFT frames with an explicit streaming OLA."""
    window = torch.hann_window(window_size, device=spec.device, dtype=spec.real.dtype)
    time_frames = torch.fft.irfft(spec, n=window_size, dim=-2)
    time_frames = time_frames * window.view(1, 1, -1, 1)
    frame_count = spec.shape[-1]
    padded_length = (frame_count - 1) * hop + window_size
    output = torch.zeros(*spec.shape[:-2], padded_length, device=spec.device)
    denominator = torch.zeros(padded_length, device=spec.device)
    for index in range(frame_count):
        start = index * hop
        output[..., start : start + window_size] += time_frames[..., index]
        denominator[start : start + window_size] += window.square()
    output = output / denominator.clamp_min(1e-11)
    center_pad = window_size // 2
    return output[..., center_pad:-center_pad]


def aligned_snr(reference: torch.Tensor, estimate: torch.Tensor) -> float:
    length = min(reference.numel(), estimate.numel())
    reference = reference.reshape(-1)[:length].cpu().double()
    estimate = estimate.reshape(-1)[:length].cpu().double()
    error = reference - estimate
    return float(10 * torch.log10(reference.square().sum() / error.square().sum()))


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(values), q))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--mixture", type=Path, required=True)
    parser.add_argument("--enrollment", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--frames-per-chunk", type=int, default=4)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args()

    sys.path.insert(0, str(args.repo))
    import wesep  # noqa: PLC0415

    extractor = wesep.load_model_local(str(args.model_dir))
    model = extractor.model.eval()
    sample_rate = extractor.resample_rate
    mixture = load_audio(args.mixture, sample_rate)
    enrollment = load_audio(args.enrollment, sample_rate)
    device = torch.device(args.device)
    model = model.to(device)
    mixture = mixture.to(device)
    enrollment = enrollment.to(device)

    with torch.inference_mode():
        synchronize(device)
        start = time.perf_counter()
        features, mixture_subbands, conditioning, whole_input_spec = prepare_features(
            model, mixture, enrollment
        )
        synchronize(device)
        feature_seconds = time.perf_counter() - start

        synchronize(device)
        start = time.perf_counter()
        whole_separated = model.sep_model.separator(features)
        whole_spec = mask_frames(model, whole_separated, mixture_subbands)
        whole_audio = model.sep_model.istft(whole_spec)
        synchronize(device)
        whole_seconds = time.perf_counter() - start

        states = [None] * len(model.sep_model.separator.separation)
        spec_chunks = []
        durations_ms = []
        for frame_start in range(0, features.shape[-1], args.frames_per_chunk):
            frame_end = min(frame_start + args.frames_per_chunk, features.shape[-1])
            chunk_features = features[..., frame_start:frame_end]
            chunk_mixture = [part[..., frame_start:frame_end] for part in mixture_subbands]
            synchronize(device)
            start = time.perf_counter()
            separated, states = separator_chunk(
                model.sep_model.separator, chunk_features, states
            )
            spec_chunks.append(mask_frames(model, separated, chunk_mixture))
            synchronize(device)
            durations_ms.append((time.perf_counter() - start) * 1000)

        chunked_spec = torch.cat(spec_chunks, dim=-1)
        chunked_audio = model.sep_model.istft(chunked_spec)
        ola_audio = streaming_overlap_add(
            chunked_spec, model.sep_model.win, model.sep_model.stride
        )

        stream_stft = StreamingSTFT(model.sep_model.win, model.sep_model.stride, device)
        stream_ola = StreamingOLA(model.sep_model.win, model.sep_model.stride, device)
        pending_frames = []
        waveform_outputs = []
        waveform_states = [None] * len(model.sep_model.separator.separation)
        waveform_spec_frames = []
        waveform_compute_seconds = 0.0

        def process_pending(force: bool = False) -> None:
            nonlocal pending_frames, waveform_states, waveform_compute_seconds
            while len(pending_frames) >= args.frames_per_chunk or (force and pending_frames):
                count = min(args.frames_per_chunk, len(pending_frames))
                spec_chunk = torch.cat(pending_frames[:count], dim=-1)
                pending_frames = pending_frames[count:]
                synchronize(device)
                chunk_start = time.perf_counter()
                stream_features, stream_mixture = condition_features(
                    model, spec_chunk, conditioning
                )
                stream_separated, waveform_states = separator_chunk(
                    model.sep_model.separator, stream_features, waveform_states
                )
                estimated_spec = mask_frames(
                    model, stream_separated, stream_mixture
                )
                waveform_spec_frames.append(estimated_spec)
                waveform_outputs.extend(stream_ola.push(estimated_spec))
                synchronize(device)
                waveform_compute_seconds += time.perf_counter() - chunk_start

        input_hop = model.sep_model.stride
        for sample_start in range(0, mixture.shape[-1], input_hop):
            pending_frames.extend(
                stream_stft.push(mixture[..., sample_start : sample_start + input_hop])
            )
            process_pending()
        pending_frames.extend(stream_stft.flush())
        process_pending(force=True)
        waveform_outputs.extend(stream_ola.flush())
        waveform_audio = torch.cat(waveform_outputs, dim=-1)
        waveform_spec = torch.cat(waveform_spec_frames, dim=-1)

    sample_seconds = mixture.shape[-1] / sample_rate
    compute_seconds = sum(durations_ms) / 1000
    max_abs = float((whole_audio - chunked_audio).abs().max().cpu())
    result = {
        "source_commit": "2a540977a348fbaa92e623210505430e2cec608d",
        "model_sha256": sha256(args.model_dir / "avg_model.pt"),
        "device": str(device),
        "sample_rate": sample_rate,
        "audio_seconds": sample_seconds,
        "stft_frames": features.shape[-1],
        "frames_per_chunk": args.frames_per_chunk,
        "chunk_audio_ms": args.frames_per_chunk * model.sep_model.stride * 1000 / sample_rate,
        "algorithmic_latency_ms": (
            model.sep_model.win - model.sep_model.stride
        ) * 1000 / sample_rate,
        "feature_and_enrollment_seconds": feature_seconds,
        "whole_separator_mask_istft_seconds": whole_seconds,
        "chunk_compute_seconds": compute_seconds,
        "chunk_compute_rtf": compute_seconds / sample_seconds,
        "chunk_call_ms_p50": percentile(durations_ms, 50),
        "chunk_call_ms_p95": percentile(durations_ms, 95),
        "chunk_call_ms_max": max(durations_ms),
        "whole_chunked_max_abs": max_abs,
        "whole_chunked_aligned_snr_db": aligned_snr(whole_audio, chunked_audio),
        "torch_istft_ola_max_abs": float(
            (chunked_audio - ola_audio).abs().max().cpu()
        ),
        "torch_istft_ola_aligned_snr_db": aligned_snr(chunked_audio, ola_audio),
        "streaming_output_spec_max_abs": float(
            (chunked_spec - waveform_spec).abs().max().cpu()
        ),
        "waveform_stream_compute_seconds": waveform_compute_seconds,
        "waveform_stream_compute_rtf": waveform_compute_seconds / sample_seconds,
        "whole_waveform_stream_max_abs": float(
            (whole_audio - waveform_audio).abs().max().cpu()
        ),
        "whole_waveform_stream_aligned_snr_db": aligned_snr(
            whole_audio, waveform_audio
        ),
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
