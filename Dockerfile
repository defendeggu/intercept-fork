# INTERCEPT - Signal Intelligence Platform
# Docker container for running the web interface

FROM python:3.11-slim

LABEL maintainer="INTERCEPT Project"
LABEL description="Signal Intelligence Platform for SDR monitoring"

# Set working directory
WORKDIR /app

# Install system dependencies for SDR tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    # RTL-SDR tools
    rtl-sdr \
    librtlsdr-dev \
    libusb-1.0-0-dev \
    # 433MHz decoder
    rtl-433 \
    # Pager decoder
    multimon-ng \
    # Audio tools for Listening Post
    ffmpeg \
    # WiFi tools (aircrack-ng suite)
    aircrack-ng \
    iw \
    wireless-tools \
    # Bluetooth tools
    bluez \
    bluetooth \
    # GPS support
    gpsd-clients \
    # Utilities
    curl \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Build dump1090-fa and acarsdec from source (packages not available in slim repos)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    pkg-config \
    cmake \
    libncurses-dev \
    libsndfile1-dev \
    # Build dump1090
    && cd /tmp \
    && git clone --depth 1 https://github.com/flightaware/dump1090.git \
    && cd dump1090 \
    && make \
    && cp dump1090 /usr/bin/dump1090-fa \
    && ln -s /usr/bin/dump1090-fa /usr/bin/dump1090 \
    && rm -rf /tmp/dump1090 \
    # Build acarsdec
    && cd /tmp \
    && git clone --depth 1 https://github.com/TLeconte/acarsdec.git \
    && cd acarsdec \
    && mkdir build && cd build \
    && cmake .. -Drtl=ON \
    && make \
    && cp acarsdec /usr/bin/acarsdec \
    && rm -rf /tmp/acarsdec \
    # Cleanup build tools to reduce image size
    && apt-get remove -y \
        build-essential \
        git \
        pkg-config \
        cmake \
        libncurses-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory for persistence
RUN mkdir -p /app/data

# Expose web interface port
EXPOSE 5050

# Environment variables with defaults
ENV INTERCEPT_HOST=0.0.0.0 \
    INTERCEPT_PORT=5050 \
    INTERCEPT_LOG_LEVEL=INFO \
    PYTHONUNBUFFERED=1

# Health check using the new endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -sf http://localhost:5050/health || exit 1

# Run the application
CMD ["python", "intercept.py"]
