# INTERCEPT - Signal Intelligence Platform
# Docker container for running the web interface

FROM python:3.11-slim

LABEL maintainer="INTERCEPT Project"
LABEL description="Signal Intelligence Platform for SDR monitoring"

# Set working directory
WORKDIR /app

# Pre-accept tshark non-root capture prompt for non-interactive install
RUN echo 'wireshark-common wireshark-common/install-setuid boolean true' | debconf-set-selections

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
    # SSTV decoder runtime libs
    libsndfile1 \
    # SatDump runtime libs (weather satellite decoding)
    libpng16-16 \
    libtiff6 \
    libjemalloc2 \
    libvolk-bin \
    libnng1 \
    libzstd1 \
    # WiFi tools (aircrack-ng suite)
    aircrack-ng \
    iw \
    wireless-tools \
    # Bluetooth tools
    bluez \
    bluetooth \
    # GPS support
    gpsd \
    gpsd-clients \
    # Utilities
    # APRS
    direwolf \
    # WiFi Extra
    hcxdumptool \
    hcxtools \
    # SDR Hardware & SoapySDR
    soapysdr-tools \
    soapysdr-module-rtlsdr \
    soapysdr-module-hackrf \
    soapysdr-module-lms7 \
    soapysdr-module-airspy \
    airspy \
    limesuite \
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
    # GTK is required for slowrx (SSTV decoder GUI dependency).
    # Note: slowrx is kept for backwards compatibility, but the pure Python
    # SSTV decoder in utils/sstv/ is now the primary implementation.
    # GTK can be removed if slowrx is deprecated in future releases.
    libgtk-3-dev \
    libasound2-dev \
    libsoapysdr-dev \
    libhackrf-dev \
    liblimesuite-dev \
    libfftw3-dev \
    libpng-dev \
    libtiff-dev \
    libjemalloc-dev \
    libvolk-dev \
    libnng-dev \
    libzstd-dev \
    libsqlite3-dev \
    libcurl4-openssl-dev \
    zlib1g-dev \
    libzmq3-dev \
    libpulse-dev \
    libfftw3-dev \
    liblapack-dev \
    libglib2.0-dev \
    libxml2-dev \
    # Build dump1090
    && cd /tmp \
    && git clone --depth 1 https://github.com/flightaware/dump1090.git \
    && cd dump1090 \
    && sed -i 's/-Werror//g' Makefile \
    && make BLADERF=no RTLSDR=yes \
    && cp dump1090 /usr/bin/dump1090-fa \
    && ln -s /usr/bin/dump1090-fa /usr/bin/dump1090 \
    && rm -rf /tmp/dump1090 \
    # Build AIS-catcher
    && cd /tmp \
    && git clone https://github.com/jvde-github/AIS-catcher.git \
    && cd AIS-catcher \
    && mkdir build && cd build \
    && cmake .. \
    && make \
    && cp AIS-catcher /usr/bin/AIS-catcher \
    && cd /tmp \
    && rm -rf /tmp/AIS-catcher \
    # Build readsb
    && cd /tmp \
    && git clone --depth 1 https://github.com/wiedehopf/readsb.git \
    && cd readsb \
    && make BLADERF=no PLUTOSDR=no SOAPYSDR=yes \
    && cp readsb /usr/bin/readsb \
    && cd /tmp \
    && rm -rf /tmp/readsb \
    # Build rx_tools
    && cd /tmp \
    && git clone https://github.com/rxseger/rx_tools.git \
    && cd rx_tools \
    && mkdir build && cd build \
    && cmake .. \
    && make \
    && make install \
    && cd /tmp \
    && rm -rf /tmp/rx_tools \
    # Build acarsdec
    && cd /tmp \
    && git clone --depth 1 https://github.com/TLeconte/acarsdec.git \
    && cd acarsdec \
    && mkdir build && cd build \
    && cmake .. -Drtl=ON -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
    && make \
    && cp acarsdec /usr/bin/acarsdec \
    && rm -rf /tmp/acarsdec \
    # Build libacars (required by dumpvdl2)
    && cd /tmp \
    && git clone --depth 1 https://github.com/szpajder/libacars.git \
    && cd libacars \
    && mkdir build && cd build \
    && cmake .. \
    && make \
    && make install \
    && ldconfig \
    && rm -rf /tmp/libacars \
    # Build dumpvdl2 (VDL2 aircraft datalink decoder)
    && cd /tmp \
    && git clone --depth 1 https://github.com/szpajder/dumpvdl2.git \
    && cd dumpvdl2 \
    && mkdir build && cd build \
    && cmake .. \
    && make \
    && cp src/dumpvdl2 /usr/bin/dumpvdl2 \
    && rm -rf /tmp/dumpvdl2 \
    # Build slowrx (SSTV decoder) — pinned to known-good commit
    && cd /tmp \
    && git clone https://github.com/windytan/slowrx.git \
    && cd slowrx \
    && git checkout ca6d7012 \
    && make \
    && install -m 0755 slowrx /usr/local/bin/slowrx \
    && rm -rf /tmp/slowrx \
    # Build SatDump (weather satellite decoder - NOAA APT & Meteor LRPT) — pinned to v1.2.2
    && cd /tmp \
    && git clone --depth 1 --branch 1.2.2 https://github.com/SatDump/SatDump.git \
    && cd SatDump \
    && mkdir build && cd build \
    && cmake -DCMAKE_BUILD_TYPE=Release -DBUILD_GUI=OFF -DCMAKE_INSTALL_LIBDIR=lib .. \
    && make -j$(nproc) \
    && make install \
    && ldconfig \
    # Ensure SatDump plugins are in the expected path (handles multiarch differences)
    && mkdir -p /usr/local/lib/satdump/plugins \
    && if [ -z "$(ls /usr/local/lib/satdump/plugins/*.so 2>/dev/null)" ]; then \
        for dir in /usr/local/lib/*/satdump/plugins /usr/lib/*/satdump/plugins /usr/lib/satdump/plugins; do \
            if [ -d "$dir" ] && [ -n "$(ls "$dir"/*.so 2>/dev/null)" ]; then \
                ln -sf "$dir"/*.so /usr/local/lib/satdump/plugins/; \
                break; \
            fi; \
        done; \
    fi \
    && cd /tmp \
    && rm -rf /tmp/SatDump \
    # Build hackrf CLI tools from source — avoids libhackrf0 version conflict
    # between the 'hackrf' apt package and soapysdr-module-hackrf's newer libhackrf0
    && cd /tmp \
    && git clone --depth 1 https://github.com/greatscottgadgets/hackrf.git \
    && cd hackrf/host \
    && mkdir build && cd build \
    && cmake .. \
    && make \
    && make install \
    && ldconfig \
    && rm -rf /tmp/hackrf \
    # Build rtlamr (utility meter decoder - requires Go)
    && cd /tmp \
    && curl -fsSL "https://go.dev/dl/go1.22.5.linux-$(dpkg --print-architecture).tar.gz" | tar -C /usr/local -xz \
    && export PATH="$PATH:/usr/local/go/bin" \
    && export GOPATH=/tmp/gopath \
    && go install github.com/bemasher/rtlamr@latest \
    && cp /tmp/gopath/bin/rtlamr /usr/bin/rtlamr \
    && rm -rf /usr/local/go /tmp/gopath \
    # Cleanup build tools to reduce image size
    # libgtk-3-dev is explicitly removed; runtime GTK libs remain for slowrx
    && apt-get remove -y \
    build-essential \
    git \
    pkg-config \
    cmake \
    libncurses-dev \
    libsndfile1-dev \
    libgtk-3-dev \
    libasound2-dev \
    libpng-dev \
    libtiff-dev \
    libjemalloc-dev \
    libvolk-dev \
    libnng-dev \
    libzstd-dev \
    libsoapysdr-dev \
    libhackrf-dev \
    liblimesuite-dev \
    libsqlite3-dev \
    libcurl4-openssl-dev \
    zlib1g-dev \
    libzmq3-dev \
    libpulse-dev \
    libfftw3-dev \
    liblapack-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory for persistence
RUN mkdir -p /app/data /app/data/weather_sat

# Expose web interface port
EXPOSE 5050
EXPOSE 5443

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
