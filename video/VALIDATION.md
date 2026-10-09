# Validation — 2026-10-07

- Composition: `MicForYouPromo`, 1920×1080, 30 fps, 1260 frames / 42 seconds.
- `npm run lint`: TypeScript compilation check passed.
- Reviewed eight rendered stills spanning all six scenes and three menu states.
- Fixed clipped desktop lettering, an overlapping waveform annotation, and a
  wrapping scene-counter label; reviewed the affected frames after correction.
- Extracted and inspected a contact sheet from the actual encoded MP4, sampling
  every two seconds. This is visual spot checking, not a claim of full playback.
- `ffprobe`: H.264 video and AAC audio both have a 42.000000-second duration.
- Final MP4: 4,244,599 bytes; full `ffmpeg` decode finished with exit code 0 and
  no error output.
- Export workflow completed successfully. GIF: 1920×1080, 1260 frames,
  42.000000 seconds, 41,571,477 bytes. PNG preview exists and was visually
  inspected after export.
- Original soundtrack was mastered with local FFmpeg to -20 LUFS. Before the
  final 100 ms tail trim, measured integrated loudness was -20.00 LUFS and true
  peak -8.12 dBTP. Audio checks are measurements, not a listening review.
- No voice recording, microphone capture, external video model, cloud audio
  service or private product test recording was used.

## Limits

The interface is an animation based on source code, not captured application
behavior. Waveforms do not demonstrate measured filter quality. The film retains
the Experimental Alpha identity and the target-absent quality limitation. It has
original procedural music and UI effects, with no spoken narration.
