#!/bin/bash
# INTERCEPT - Multi-architecture Docker image builder
#
# Builds for both linux/amd64 and linux/arm64 using Docker buildx.
# Run this on your x64 machine to cross-compile the arm64 image
# instead of building natively on the RPi5.
#
# Prerequisites (one-time setup):
#   docker run --privileged --rm tonistiigi/binfmt --install all
#   docker buildx create --name intercept-builder --use --bootstrap
#
# Usage:
#   ./build-multiarch.sh                    # Build both platforms, load locally
#   ./build-multiarch.sh --push             # Build and push to registry
#   ./build-multiarch.sh --arm64-only       # Build arm64 only (for RPi)
#   REGISTRY=ghcr.io/user ./build-multiarch.sh --push
#
# Environment variables:
#   REGISTRY    - Container registry (default: docker.io/library)
#   IMAGE_NAME  - Image name (default: intercept)
#   IMAGE_TAG   - Image tag (default: latest)

set -euo pipefail

# Configuration
REGISTRY="${REGISTRY:-}"
IMAGE_NAME="${IMAGE_NAME:-intercept}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
BUILDER_NAME="intercept-builder"
PLATFORMS="linux/amd64,linux/arm64"

# Parse arguments
PUSH=false
LOAD=false
ARM64_ONLY=false

for arg in "$@"; do
    case $arg in
        --push)     PUSH=true ;;
        --load)     LOAD=true ;;
        --arm64-only)
            ARM64_ONLY=true
            PLATFORMS="linux/arm64"
            ;;
        --amd64-only)
            PLATFORMS="linux/amd64"
            ;;
        --help|-h)
            echo "Usage: $0 [--push] [--load] [--arm64-only] [--amd64-only]"
            echo ""
            echo "Options:"
            echo "  --push        Push to container registry"
            echo "  --load        Load into local Docker (single platform only)"
            echo "  --arm64-only  Build arm64 only (for RPi5 deployment)"
            echo "  --amd64-only  Build amd64 only"
            echo ""
            echo "Environment variables:"
            echo "  REGISTRY    Container registry (e.g. ghcr.io/username)"
            echo "  IMAGE_NAME  Image name (default: intercept)"
            echo "  IMAGE_TAG   Image tag (default: latest)"
            echo ""
            echo "Examples:"
            echo "  $0 --push                                    # Build both, push"
            echo "  REGISTRY=ghcr.io/myuser $0 --push            # Push to GHCR"
            echo "  $0 --arm64-only --load                       # Build arm64, load locally"
            echo "  $0 --arm64-only --push && ssh rpi docker pull # Build + deploy to RPi"
            exit 0
            ;;
        *)
            echo "Unknown option: $arg"
            exit 1
            ;;
    esac
done

# Build full image reference
if [ -n "$REGISTRY" ]; then
    FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"
else
    FULL_IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"
fi

echo "============================================"
echo "  INTERCEPT Multi-Architecture Builder"
echo "============================================"
echo "  Image:     ${FULL_IMAGE}"
echo "  Platforms: ${PLATFORMS}"
echo "  Push:      ${PUSH}"
echo "============================================"
echo ""

# Check if buildx builder exists, create if not
if ! docker buildx inspect "$BUILDER_NAME" >/dev/null 2>&1; then
    echo "Creating buildx builder: ${BUILDER_NAME}"
    docker buildx create --name "$BUILDER_NAME" --use --bootstrap

    # Check for QEMU support
    if ! docker run --rm --privileged tonistiigi/binfmt --install all >/dev/null 2>&1; then
        echo "WARNING: QEMU binfmt setup may have failed."
        echo "Run: docker run --privileged --rm tonistiigi/binfmt --install all"
    fi
else
    docker buildx use "$BUILDER_NAME"
fi

# Build command
BUILD_CMD="docker buildx build --platform ${PLATFORMS} --tag ${FULL_IMAGE}"

if [ "$PUSH" = true ]; then
    BUILD_CMD="${BUILD_CMD} --push"
    echo "Will push to: ${FULL_IMAGE}"
elif [ "$LOAD" = true ]; then
    # --load only works with single platform
    if echo "$PLATFORMS" | grep -q ","; then
        echo "ERROR: --load only works with a single platform."
        echo "Use --arm64-only or --amd64-only with --load."
        exit 1
    fi
    BUILD_CMD="${BUILD_CMD} --load"
    echo "Will load into local Docker"
fi

echo ""
echo "Building..."
echo "Command: ${BUILD_CMD} ."
echo ""

$BUILD_CMD .

echo ""
echo "============================================"
echo "  Build complete!"
if [ "$PUSH" = true ]; then
    echo "  Image pushed to: ${FULL_IMAGE}"
    echo ""
    echo "  Pull on RPi5:"
    echo "    docker pull ${FULL_IMAGE}"
fi
echo "============================================"
