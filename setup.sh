#!/bin/bash
#
# INTERCEPT Setup Script
# Installs dependencies for macOS and Debian/Ubuntu
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "  ___ _   _ _____ _____ ____   ____ _____ ____ _____ "
echo " |_ _| \\ | |_   _| ____|  _ \\ / ___| ____|  _ \\_   _|"
echo "  | ||  \\| | | | |  _| | |_) | |   |  _| | |_) || |  "
echo "  | || |\\  | | | | |___|  _ <| |___| |___|  __/ | |  "
echo " |___|_| \\_| |_| |_____|_| \\_\\\\____|_____|_|    |_|  "
echo -e "${NC}"
echo "Signal Intelligence Platform - Setup Script"
echo "============================================"
echo ""

# Detect OS
detect_os() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        OS="macos"
        PKG_MANAGER="brew"
    elif [[ -f /etc/debian_version ]]; then
        OS="debian"
        PKG_MANAGER="apt"
    else
        OS="unknown"
        PKG_MANAGER="unknown"
    fi
    echo -e "${BLUE}Detected OS:${NC} $OS"
}

# Check if a command exists
check_cmd() {
    command -v "$1" &> /dev/null
}

# Check if a package is installable (Debian)
pkg_available() {
    local candidate
    candidate=$(apt-cache policy "$1" 2>/dev/null | grep "Candidate:" | awk '{print $2}')
    [ -n "$candidate" ] && [ "$candidate" != "(none)" ]
}

# Setup sudo command
setup_sudo() {
    if [ "$(id -u)" -eq 0 ]; then
        SUDO=""
        echo -e "${BLUE}Running as root${NC}"
    elif check_cmd sudo; then
        SUDO="sudo"
    else
        echo -e "${RED}Error: Not running as root and sudo is not installed${NC}"
        exit 1
    fi
}

# ============================================
# PYTHON DEPENDENCIES
# ============================================
install_python_deps() {
    echo ""
    echo -e "${BLUE}[1/3] Installing Python dependencies...${NC}"

    if ! check_cmd python3; then
        echo -e "${RED}Error: Python 3 is not installed${NC}"
        if [[ "$OS" == "macos" ]]; then
            echo "Install with: brew install python@3.11"
        else
            echo "Install with: sudo apt install python3"
        fi
        exit 1
    fi

    # Check Python version
    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PYTHON_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
    PYTHON_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
    echo "Python version: $PYTHON_VERSION"

    if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 9 ]); then
        echo -e "${RED}Error: Python 3.9 or later is required (you have $PYTHON_VERSION)${NC}"
        if [[ "$OS" == "macos" ]]; then
            echo "Upgrade with: brew install python@3.11"
        else
            echo "Upgrade with: sudo apt install python3.11"
        fi
        exit 1
    fi

    # Install dependencies
    if [ -n "$VIRTUAL_ENV" ]; then
        echo "Using virtual environment: $VIRTUAL_ENV"
        pip install -r requirements.txt
    elif [ -f "venv/bin/activate" ]; then
        echo "Found existing venv, activating..."
        source venv/bin/activate
        pip install -r requirements.txt
    else
        # Try pip install, fall back to venv if needed (PEP 668)
        if python3 -m pip install -r requirements.txt 2>/dev/null; then
            echo -e "${GREEN}Python dependencies installed${NC}"
            return
        fi

        echo -e "${YELLOW}Creating virtual environment...${NC}"
        if [ -d "venv" ] && [ ! -f "venv/bin/activate" ]; then
            rm -rf venv
        fi

        if ! python3 -m venv venv; then
            echo -e "${RED}Error: Failed to create virtual environment${NC}"
            if [[ "$OS" == "debian" ]]; then
                echo "Install with: sudo apt install python3-venv"
            fi
            exit 1
        fi

        source venv/bin/activate
        pip install -r requirements.txt

        echo ""
        echo -e "${YELLOW}NOTE: Virtual environment created.${NC}"
        echo "Activate with: source venv/bin/activate"
    fi

    echo -e "${GREEN}Python dependencies installed${NC}"
}

# ============================================
# TOOL CHECKING
# ============================================
check_tool() {
    local cmd=$1
    local desc=$2
    local category=$3
    if check_cmd "$cmd"; then
        echo -e "  ${GREEN}✓${NC} $cmd - $desc"
        return 0
    else
        echo -e "  ${RED}✗${NC} $cmd - $desc ${YELLOW}(not found)${NC}"
        MISSING_TOOLS+=("$cmd")
        case "$category" in
            core) MISSING_CORE=true ;;
            audio) MISSING_AUDIO=true ;;
            wifi) MISSING_WIFI=true ;;
            bluetooth) MISSING_BLUETOOTH=true ;;
        esac
        return 1
    fi
}

check_tools() {
    echo ""
    echo -e "${BLUE}[2/3] Checking external tools...${NC}"
    echo ""

    MISSING_TOOLS=()
    MISSING_CORE=false
    MISSING_AUDIO=false
    MISSING_WIFI=false
    MISSING_BLUETOOTH=false

    echo "Core SDR Tools:"
    check_tool "rtl_fm" "RTL-SDR FM demodulator" "core"
    check_tool "rtl_test" "RTL-SDR device detection" "core"
    check_tool "multimon-ng" "Pager decoder" "core"
    check_tool "rtl_433" "433MHz sensor decoder" "core"
    check_tool "dump1090" "ADS-B decoder" "core"

    echo ""
    echo "Audio Tools:"
    check_tool "ffmpeg" "Audio encoder for streaming" "audio"

    echo ""
    echo "WiFi Tools:"
    check_tool "airmon-ng" "WiFi monitor mode" "wifi"
    check_tool "airodump-ng" "WiFi scanner" "wifi"
    # aireplay-ng is optional (for deauth)
    if check_cmd aireplay-ng; then
        echo -e "  ${GREEN}✓${NC} aireplay-ng - Deauthentication (optional)"
    fi

    echo ""
    echo "Bluetooth Tools:"
    check_tool "hcitool" "Bluetooth scanner" "bluetooth"
    check_tool "bluetoothctl" "Bluetooth controller" "bluetooth"
    check_tool "hciconfig" "Bluetooth adapter config" "bluetooth"

    echo ""
    echo "Optional (LimeSDR/HackRF):"
    if check_cmd SoapySDRUtil; then
        echo -e "  ${GREEN}✓${NC} SoapySDRUtil - SoapySDR support"
    else
        echo -e "  ${YELLOW}-${NC} SoapySDRUtil - Not installed (optional)"
    fi

    if [ ${#MISSING_TOOLS[@]} -gt 0 ]; then
        echo ""
        echo -e "${YELLOW}Some tools are missing.${NC}"
    else
        echo ""
        echo -e "${GREEN}All tools installed!${NC}"
    fi
}

# ============================================
# macOS INSTALLATION
# ============================================
install_macos_tools() {
    echo ""
    echo -e "${BLUE}[3/3] Installing tools (macOS)...${NC}"
    echo ""

    if [ ${#MISSING_TOOLS[@]} -eq 0 ]; then
        echo -e "${GREEN}All tools are already installed!${NC}"
        return
    fi

    # Check for Homebrew
    if ! check_cmd brew; then
        echo -e "${YELLOW}Homebrew is not installed. Installing...${NC}"
        echo ""
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

        # Add brew to PATH for this session
        if [[ -f /opt/homebrew/bin/brew ]]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        elif [[ -f /usr/local/bin/brew ]]; then
            eval "$(/usr/local/bin/brew shellenv)"
        fi

        if ! check_cmd brew; then
            echo -e "${RED}Failed to install Homebrew. Install manually:${NC}"
            show_macos_manual
            return
        fi
    fi

    echo -e "${YELLOW}Installing missing tools automatically...${NC}"
    echo ""

    # Core SDR tools
    if $MISSING_CORE; then
        echo ""
        echo -e "${BLUE}Installing Core SDR tools...${NC}"

        echo "  Installing librtlsdr..."
        brew install librtlsdr || echo -e "${YELLOW}  Warning: librtlsdr installation failed${NC}"

        echo "  Installing multimon-ng..."
        brew install multimon-ng || echo -e "${YELLOW}  Warning: multimon-ng installation failed${NC}"

        echo "  Installing rtl_433..."
        brew install rtl_433 || echo -e "${YELLOW}  Warning: rtl_433 installation failed${NC}"

        # dump1090
        if ! check_cmd dump1090; then
            echo "  Installing dump1090..."
            brew install dump1090-mutability || \
            echo -e "${YELLOW}  Note: dump1090 may need manual installation${NC}"
        fi
    fi

    # Audio tools
    if $MISSING_AUDIO; then
        echo ""
        echo -e "${BLUE}Installing Audio tools...${NC}"
        echo "  Installing ffmpeg..."
        brew install ffmpeg || echo -e "${YELLOW}  Warning: ffmpeg installation failed${NC}"
    fi

    # WiFi tools
    if $MISSING_WIFI; then
        echo ""
        echo -e "${BLUE}Installing WiFi tools...${NC}"
        echo "  Installing aircrack-ng..."
        brew install aircrack-ng || echo -e "${YELLOW}  Warning: aircrack-ng installation failed${NC}"
    fi

    echo ""
    echo -e "${GREEN}Tool installation complete!${NC}"
}

show_macos_manual() {
    echo ""
    echo -e "${BLUE}Manual installation (macOS):${NC}"
    echo ""
    echo "# Required tools"
    echo "brew install librtlsdr multimon-ng rtl_433 ffmpeg"
    echo ""
    echo "# ADS-B tracking"
    echo "brew install dump1090-mutability"
    echo ""
    echo "# WiFi scanning (optional)"
    echo "brew install aircrack-ng"
}

# ============================================
# BUILD DUMP1090 FROM SOURCE
# ============================================
install_dump1090_from_source() {
    # Install build dependencies
    echo "    Installing build dependencies..."
    $SUDO apt-get install -y build-essential librtlsdr-dev libusb-1.0-0-dev pkg-config git

    # Create temp directory
    local tmp_dir=$(mktemp -d)
    cd "$tmp_dir"

    echo "    Cloning dump1090 repository..."
    if git clone https://github.com/flightaware/dump1090.git; then
        cd dump1090
        echo "    Compiling dump1090..."
        if make; then
            echo "    Installing dump1090 to /usr/local/bin..."
            $SUDO cp dump1090 /usr/local/bin/
            $SUDO chmod +x /usr/local/bin/dump1090
            echo -e "${GREEN}    dump1090 installed successfully!${NC}"
        else
            echo -e "${RED}    Failed to compile dump1090${NC}"
        fi
    else
        echo -e "${RED}    Failed to clone dump1090 repository${NC}"
    fi

    # Cleanup
    cd - > /dev/null
    rm -rf "$tmp_dir"
}

# ============================================
# DEBIAN INSTALLATION
# ============================================
install_debian_tools() {
    echo ""
    echo -e "${BLUE}[3/3] Installing tools (Debian/Ubuntu)...${NC}"
    echo ""

    if [ ${#MISSING_TOOLS[@]} -eq 0 ]; then
        echo -e "${GREEN}All tools are already installed!${NC}"
        return
    fi

    echo -e "${YELLOW}Installing missing tools automatically...${NC}"
    echo ""

    echo "Updating package lists..."
    $SUDO apt-get update

    # Core SDR tools - always try to install these
    if $MISSING_CORE; then
        echo ""
        echo -e "${BLUE}Installing Core SDR tools...${NC}"

        # Install rtl-sdr
        echo "  Installing rtl-sdr..."
        if ! $SUDO apt-get install -y rtl-sdr; then
            echo -e "${YELLOW}  Warning: rtl-sdr installation failed${NC}"
        fi

        # Install multimon-ng
        echo "  Installing multimon-ng..."
        if ! $SUDO apt-get install -y multimon-ng; then
            echo -e "${YELLOW}  Warning: multimon-ng installation failed${NC}"
        fi

        # rtl-433 (package name varies by distribution)
        echo "  Installing rtl-433..."
        if pkg_available rtl-433; then
            $SUDO apt-get install -y rtl-433
        elif pkg_available rtl433; then
            $SUDO apt-get install -y rtl433
        else
            echo -e "${YELLOW}  Note: rtl-433 not in repositories${NC}"
            echo "  Install manually from: https://github.com/merbanan/rtl_433"
        fi

        # dump1090 (package varies by distribution)
        if ! check_cmd dump1090; then
            echo "  Installing dump1090..."
            if pkg_available dump1090-fa; then
                $SUDO apt-get install -y dump1090-fa
            elif pkg_available dump1090-mutability; then
                $SUDO apt-get install -y dump1090-mutability
            elif pkg_available dump1090; then
                $SUDO apt-get install -y dump1090
            else
                # Build from source as fallback
                echo -e "${YELLOW}  dump1090 not in repositories, building from source...${NC}"
                install_dump1090_from_source
            fi
        fi
    fi

    # Audio tools
    if $MISSING_AUDIO; then
        echo ""
        echo -e "${BLUE}Installing Audio tools...${NC}"
        echo "  Installing ffmpeg..."
        if ! $SUDO apt-get install -y ffmpeg; then
            echo -e "${YELLOW}  Warning: ffmpeg installation failed${NC}"
        fi
    fi

    # WiFi tools
    if $MISSING_WIFI; then
        echo ""
        echo -e "${BLUE}Installing WiFi tools...${NC}"
        echo "  Installing aircrack-ng..."
        if ! $SUDO apt-get install -y aircrack-ng; then
            echo -e "${YELLOW}  Warning: aircrack-ng installation failed${NC}"
        fi
    fi

    # Bluetooth tools
    if $MISSING_BLUETOOTH; then
        echo ""
        echo -e "${BLUE}Installing Bluetooth tools...${NC}"
        echo "  Installing bluez..."
        if ! $SUDO apt-get install -y bluez bluetooth; then
            echo -e "${YELLOW}  Warning: bluez installation failed${NC}"
        fi
    fi

    echo ""
    echo -e "${GREEN}Tool installation complete!${NC}"

    # Setup udev rules
    setup_udev_rules
}

show_debian_manual() {
    echo ""
    echo -e "${BLUE}Manual installation (Debian/Ubuntu):${NC}"
    echo ""
    echo "# Required tools"
    echo "sudo apt install rtl-sdr multimon-ng rtl-433 ffmpeg"
    echo ""
    echo "# ADS-B tracking"
    echo "sudo apt install dump1090-mutability  # or dump1090-fa"
    echo ""
    echo "# WiFi scanning (optional)"
    echo "sudo apt install aircrack-ng"
    echo ""
    echo "# Bluetooth scanning (optional)"
    echo "sudo apt install bluez bluetooth"
}

setup_udev_rules() {
    if [ -f /etc/udev/rules.d/20-rtlsdr.rules ]; then
        echo -e "${GREEN}udev rules already configured${NC}"
        return
    fi

    echo ""
    echo -e "${BLUE}Setting up RTL-SDR udev rules...${NC}"
    $SUDO bash -c 'cat > /etc/udev/rules.d/20-rtlsdr.rules << EOF
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", MODE="0666"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2832", MODE="0666"
EOF'
    $SUDO udevadm control --reload-rules
    $SUDO udevadm trigger
    echo -e "${GREEN}udev rules installed!${NC}"
    echo "Please unplug and replug your RTL-SDR if connected."
}

# ============================================
# MAIN
# ============================================
main() {
    detect_os

    if [[ "$OS" == "unknown" ]]; then
        echo -e "${RED}Unsupported OS. This script supports macOS and Debian/Ubuntu.${NC}"
        exit 1
    fi

    if [[ "$OS" == "debian" ]]; then
        setup_sudo
    fi

    install_python_deps
    check_tools

    if [[ "$OS" == "macos" ]]; then
        install_macos_tools
    else
        install_debian_tools
    fi

    echo ""
    echo "============================================"
    echo -e "${GREEN}Setup complete!${NC}"
    echo ""
    echo "To start INTERCEPT:"

    if [ -d "venv" ]; then
        echo "  source venv/bin/activate"
        if [[ "$OS" == "debian" ]]; then
            echo "  sudo venv/bin/python intercept.py"
        else
            echo "  sudo python3 intercept.py"
        fi
    else
        if [[ "$OS" == "debian" ]]; then
            echo "  sudo python3 intercept.py"
        else
            echo "  sudo python3 intercept.py"
        fi
    fi

    echo ""
    echo "Then open http://localhost:5050 in your browser"
    echo ""
}

main "$@"
