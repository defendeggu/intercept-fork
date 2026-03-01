#!/usr/bin/env bash
# Download sample NOAA APT recordings for testing the weather satellite
# test-decode feature. These are FM-demodulated audio WAV files.
#
# Usage:
#   ./download-weather-sat-samples.sh
#   docker exec intercept /app/download-weather-sat-samples.sh

set -euo pipefail

SAMPLE_DIR="$(dirname "$0")/data/weather_sat/samples"
mkdir -p "$SAMPLE_DIR"

echo "Downloading NOAA APT sample files to $SAMPLE_DIR ..."

# Full satellite pass recorded over Argentina (NOAA, 11025 Hz mono WAV)
# Source: https://github.com/martinber/noaa-apt
if [ ! -f "$SAMPLE_DIR/noaa_apt_argentina.wav" ]; then
    echo "  -> noaa_apt_argentina.wav (18 MB) ..."
    curl -fSL -o "$SAMPLE_DIR/noaa_apt_argentina.wav" \
        "https://noaa-apt.mbernardi.com.ar/examples/argentina.wav"
else
    echo "  -> noaa_apt_argentina.wav (already exists)"
fi

echo ""
echo "Done. Test decode with:"
echo "  Satellite:    NOAA-18"
echo "  File path:    data/weather_sat/samples/noaa_apt_argentina.wav"
echo "  Sample rate:  11025 Hz"
