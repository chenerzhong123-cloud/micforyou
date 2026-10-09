# Production evidence

## Method

Remotion's official documentation supports code-authored video with coding
agents, local preview, and rendering:

- https://www.remotion.dev/docs/
- https://www.remotion.dev/docs/ai/skills
- https://www.remotion.dev/docs/api

A directly relevant Claude Opus 5.5 creator report describes code-drawn HTML
Canvas animation, browser rendering and FFmpeg encoding; local Kokoro TTS and
Whisper were used for that creator's speech and transcription. This is a creator
disclosure, not an independently reproduced benchmark, and the user did not
identify that post as the exact example they saw:

- https://www.reddit.com/r/ClaudeAI/comments/1wpr8ea/a_made_entirely_with_opus_55_explainer_video_with/

This production uses Remotion/React/SVG instead of that creator's custom Canvas
engine, and procedural Python synthesis instead of sampled music or narration.
No voice model, video-generation model or external media service is used.

## Product sources

- `../README.md`: validated runtime and filtering limits.
- `../docs/APP_EXPERIENCE.md`: menu structure, local processing, microphone handling.
- `../app/MicForYouMenuBar/Sources/MicForYouMenuBar/MenuContentView.swift`:
  menu labels, state transitions, controls and route text.
- `../app/MicForYouMenuBar/Sources/MicForYouMenuBar/SettingsView.swift`:
  Alpha quality warning and enrollment behavior.

The film is an illustrative product promo, not measured quality evidence.
