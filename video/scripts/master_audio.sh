#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source_file="${1:-out/micforyou-promo-v4.mp4}"
mastered_file="${source_file%.mp4}-mastered.mp4"
video_duration="$(ffprobe -v error -select_streams v:0 -show_entries stream=duration -of default=noprint_wrappers=1:nokey=1 "$source_file")"
ffmpeg -hide_banner -loglevel error -y \
  -i "$source_file" \
  -af 'loudnorm=I=-20:TP=-2:LRA=7' \
  -c:v copy -c:a aac -b:a 192k -ar 48000 -t "$video_duration" -movflags +faststart \
  "$mastered_file"
mv "$mastered_file" "$source_file"
