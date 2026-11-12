#!/bin/sh
# Downloads the standalone yt-dlp macOS binary (no Python or ffmpeg needed) into worker/bin/.
set -eu
cd "$(dirname "$0")"
mkdir -p bin
base=https://github.com/yt-dlp/yt-dlp/releases/latest/download
curl -fL --proto '=https' -o bin/yt-dlp_macos "$base/yt-dlp_macos"
curl -fsL --proto '=https' "$base/SHA2-256SUMS" | grep ' yt-dlp_macos$' | (cd bin && shasum -a 256 -c -)
mv bin/yt-dlp_macos bin/yt-dlp
chmod +x bin/yt-dlp
echo "yt-dlp $(bin/yt-dlp --version) installed in $(pwd)/bin"
