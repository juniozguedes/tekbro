#!/bin/sh
# Records 6 s of system audio while macOS speaks, and reports what was captured.
cd "$(dirname "$0")/.."
[ -x bin/tekbro-audio ] || ./native/build.sh
TEKBRO_AUDIO_DEBUG=1 bin/tekbro-audio > build/test.pcm 2> build/test.err &
P=$!
sleep 1.5
say -v Samantha "Can you explain how a hash map works?"
sleep 1
kill $P 2>/dev/null
cat build/test.err
BYTES=$(wc -c < build/test.pcm | tr -d ' ')
echo "captured $BYTES bytes ($(echo "$BYTES / 64000" | bc -l | cut -c1-4) s of audio)"
[ "$BYTES" -gt 0 ] && echo "OK: system audio capture works" || echo "FAIL: no audio captured"
