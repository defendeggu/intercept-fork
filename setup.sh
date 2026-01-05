#!/bin/bash
#
# INTERCEPT Setup Script
# Installs Python dependencies and checks for external tools
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
    elif [[ -f /etc/redhat-release ]]; then
        OS="redhat"
        PKG_MANAGER="dnf"
    elif [[ -f /etc/arch-release ]]; then
        OS="arch"
        PKG_MANAGER="pacman"
    else
        OS="unknown"
        PKG_MANAGER="unknown"
    fi
    echo -e "${BLUE}Detected OS:${NC} $OS (package manager: $PKG_MANAGER)"
}

# Check if a command exists
check_cmd() {
    command -v "$1" &> /dev/null
}

# Setup sudo command (empty if running as root)
setup_sudo() {
    if [ "$(id -u)" -eq 0 ]; then
        SUDO=""
        echo -e "${BLUE}Running as root${NC}"
    elif check_cmd sudo; then
        SUDO="sudo"
    else
        echo -e "${RED}Error: Not running as root and sudo is not installed${NC}"
        echo ""
        echo "Please either:"
        echo "  1. Run this script as root: su -c './setup.sh'"
        echo "  2. Install sudo: apt install sudo"
        exit 1
    fi
}

# Install Python dependencies
install_python_deps() {
    echo ""
    echo -e "${BLUE}[1/3] Installing Python dependencies...${NC}"

    if ! check_cmd python3; then
        echo -e "${RED}Error: Python 3 is not installed${NC}"
        echo "Please install Python 3.9 or later"
        exit 1
    fi

    # Check Python version (need 3.9+)
    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PYTHON_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
    PYTHON_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
    echo "Python version: $PYTHON_VERSION"

    if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 9 ]); then
        echo -e "${RED}Error: Python 3.9 or later is required${NC}"
        echo "You have Python $PYTHON_VERSION"
        echo ""
        echo "Please upgrade Python:"
        if [ -n "$SUDO" ]; then
            echo "  Ubuntu/Debian: sudo apt install python3.11"
        else
            echo "  Ubuntu/Debian: apt install python3.11"
        fi
        echo "  macOS: brew install python@3.11"
        exit 1
    fi

    # Check if we're in a virtual environment
    if [ -n "$VIRTUAL_ENV" ]; then
        echo "Using virtual environment: $VIRTUAL_ENV"
        pip install -r requirements.txt
    elif [ -f "venv/bin/activate" ]; then
        echo "Found existing venv, activating..."
        source venv/bin/activate
        pip install -r requirements.txt
    else
        # Try direct pip install first, fall back to venv if it fails (PEP 668)
        echo "Attempting to install dependencies..."
        if python3 -m pip install -r requirements.txt 2>/dev/null; then
            echo -e "${GREEN}Python dependencies installed successfully${NC}"
            return
        fi

        # If pip install failed (likely PEP 668), create a virtual environment
        echo ""
        echo -e "${YELLOW}System Python is externally managed (PEP 668).${NC}"
        echo "Creating virtual environment..."

        # Remove any incomplete venv directory from previous failed attempts
        if [ -d "venv" ] && [ ! -f "venv/bin/activate" ]; then
            echo "Removing incomplete venv directory..."
            rm -rf venv
        fi

        if ! python3 -m venv venv; then
            echo -e "${RED}Error: Failed to create virtual environment${NC}"
            echo ""
            echo "On Debian/Ubuntu, install the venv module with:"
            if [ -n "$SUDO" ]; then
                echo "  sudo apt install python3-venv"
            else
                echo "  apt install python3-venv"
            fi
            echo ""
            echo "Then run this setup script again."
            exit 1
        fi
        source venv/bin/activate
        pip install -r requirements.txt
        echo ""
        echo -e "${YELLOW}NOTE: A virtual environment was created.${NC}"
        echo "You must activate it before running INTERCEPT:"
        echo "  source venv/bin/activate"
        if [ -n "$SUDO" ]; then
            echo "  sudo venv/bin/python intercept.py"
        else
            echo "  venv/bin/python intercept.py"
        fi
    fi

    echo -e "${GREEN}Python dependencies installed successfully${NC}"
}

# Check external tools
check_tools() {
    echo ""
    echo -e "${BLUE}[2/3] Checking external tools...${NC}"
    echo ""

    MISSING_TOOLS=()
    MISSING_CORE=false
    MISSING_WIFI=false
    MISSING_BLUETOOTH=false

    # Core SDR tools
    echo "Core SDR Tools:"
    check_tool "rtl_fm" "RTL-SDR FM demodulator" "core"
    check_tool "rtl_test" "RTL-SDR device detection" "core"
    check_tool "multimon-ng" "Pager decoder" "core"
    check_tool "rtl_433" "433MHz sensor decoder" "core"
    check_tool "dump1090" "ADS-B decoder" "core"

    echo ""
    echo "Additional SDR Hardware (optional):"
    check_tool "SoapySDRUtil" "SoapySDR (for LimeSDR/HackRF)" "optional"
    check_tool "LimeUtil" "LimeSDR tools" "optional"
    check_tool "hackrf_info" "HackRF tools" "optional"

    echo ""
    echo "WiFi Tools:"
    check_tool "airmon-ng" "WiFi monitor mode" "wifi"
    check_tool "airodump-ng" "WiFi scanner" "wifi"

    echo ""
    echo "Bluetooth Tools:"
    check_tool "bluetoothctl" "Bluetooth controller" "bluetooth"
    check_tool "hcitool" "Bluetooth HCI tool" "bluetooth"

    if [ ${#MISSING_TOOLS[@]} -gt 0 ]; then
        echo ""
        echo -e "${YELLOW}Some tools are missing.${NC}"
    fi
}

check_tool() {
    local cmd=$1
    local desc=$2
    local category=$3
    if check_cmd "$cmd"; then
        echo -e "  ${GREEN}✓${NC} $cmd - $desc"
    else
        echo -e "  ${RED}✗${NC} $cmd - $desc ${YELLOW}(not found)${NC}"
        MISSING_TOOLS+=("$cmd")
        case "$category" in
            core) MISSING_CORE=true ;;
            wifi) MISSING_WIFI=true ;;
            bluetooth) MISSING_BLUETOOTH=true ;;
        esac
    fi
}

# Install tools on Debian/Ubuntu
install_debian_tools() {
    echo ""
    echo -e "${BLUE}[3/3] Installing tools...${NC}"
    echo ""

    if [ ${#MISSING_TOOLS[@]} -eq 0 ]; then
        echo -e "${GREEN}All tools are already installed!${NC}"
        return
    fi

    echo -e "${YELLOW}The following tool categories need to be installed:${NC}"
    $MISSING_CORE && echo "  - Core SDR tools (rtl-sdr, multimon-ng, rtl-433, dump1090)"
    $MISSING_WIFI && echo "  - WiFi tools (aircrack-ng)"
    $MISSING_BLUETOOTH && echo "  - Bluetooth tools (bluez)"
    echo ""

    read -p "Would you like to install missing tools automatically? [Y/n] " -n 1 -r
    echo ""

    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        echo ""
        echo "Updating package lists..."
        $SUDO apt update

        # Core SDR tools
        if $MISSING_CORE; then
            echo ""
            echo -e "${BLUE}Installing Core SDR tools...${NC}"
            $SUDO apt install -y rtl-sdr multimon-ng rtl-433 dump1090-mutability
        fi

        # WiFi tools
        if $MISSING_WIFI; then
            echo ""
            echo -e "${BLUE}Installing WiFi tools...${NC}"
            $SUDO apt install -y aircrack-ng
        fi

        # Bluetooth tools
        if $MISSING_BLUETOOTH; then
            echo ""
            echo -e "${BLUE}Installing Bluetooth tools...${NC}"
            $SUDO apt install -y bluez bluetooth
        fi

        echo ""
        echo -e "${GREEN}Tool installation complete!${NC}"

        # Setup udev rules automatically
        setup_udev_rules_auto
    else
        echo ""
        echo "Skipping automatic installation."
        show_manual_instructions
    fi
}

# Setup udev rules automatically (Debian)
setup_udev_rules_auto() {
    echo ""
    echo -e "${BLUE}Setting up RTL-SDR udev rules...${NC}"

    if [ -f /etc/udev/rules.d/20-rtlsdr.rules ]; then
        echo "udev rules already exist, skipping."
        return
    fi

    read -p "Would you like to setup RTL-SDR udev rules? [Y/n] " -n 1 -r
    echo ""

    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        $SUDO bash -c 'cat > /etc/udev/rules.d/20-rtlsdr.rules << EOF
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", MODE="0666"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2832", MODE="0666"
EOF'
        $SUDO udevadm control --reload-rules
        $SUDO udevadm trigger
        echo -e "${GREEN}udev rules installed!${NC}"
        echo "Please unplug and replug your RTL-SDR device."
    fi
}

# Show manual installation instructions
show_manual_instructions() {
    echo ""
    echo -e "${BLUE}Manual installation instructions:${NC}"
    echo ""

    if [[ "$OS" == "macos" ]]; then
        echo -e "${YELLOW}macOS (Homebrew):${NC}"
        echo ""

        if ! check_cmd brew; then
            echo "First, install Homebrew:"
            echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
            echo ""
        fi

        echo "# Core SDR tools"
        echo "brew install librtlsdr multimon-ng rtl_433 dump1090-mutability"
        echo ""
        echo "# LimeSDR support (optional)"
        echo "brew install soapysdr limesuite soapylms7"
        echo ""
        echo "# HackRF support (optional)"
        echo "brew install hackrf soapyhackrf"
        echo ""
        echo "# WiFi tools"
        echo "brew install aircrack-ng"

    elif [[ "$OS" == "debian" ]]; then
        echo -e "${YELLOW}Ubuntu/Debian:${NC}"
        echo ""
        echo "# Core SDR tools"
        echo "sudo apt update"
        echo "sudo apt install rtl-sdr multimon-ng rtl-433 dump1090-mutability"
        echo ""
        echo "# LimeSDR support (optional)"
        echo "sudo apt install soapysdr-tools limesuite soapysdr-module-lms7"
        echo ""
        echo "# HackRF support (optional)"
        echo "sudo apt install hackrf soapysdr-module-hackrf"
        echo ""
        echo "# WiFi tools"
        echo "sudo apt install aircrack-ng"
        echo ""
        echo "# Bluetooth tools"
        echo "sudo apt install bluez bluetooth"

    elif [[ "$OS" == "arch" ]]; then
        echo -e "${YELLOW}Arch Linux:${NC}"
        echo ""
        echo "# Core SDR tools"
        echo "sudo pacman -S rtl-sdr multimon-ng"
        echo "yay -S rtl_433 dump1090"
        echo ""
        echo "# LimeSDR/HackRF support (optional)"
        echo "sudo pacman -S soapysdr limesuite hackrf"

    elif [[ "$OS" == "redhat" ]]; then
        echo -e "${YELLOW}Fedora/RHEL:${NC}"
        echo ""
        echo "# Core SDR tools"
        echo "sudo dnf install rtl-sdr"
        echo "# multimon-ng, rtl_433, dump1090 may need to be built from source"

    else
        echo "Please install the following tools manually:"
        for tool in "${MISSING_TOOLS[@]}"; do
            echo "  - $tool"
        done
    fi
}

# Show installation instructions (decides auto vs manual)
install_or_show_instructions() {
    if [[ "$OS" == "debian" ]]; then
        install_debian_tools
    else
        echo ""
        echo -e "${BLUE}[3/3] Installation instructions for missing tools${NC}"
        if [ ${#MISSING_TOOLS[@]} -eq 0 ]; then
            echo ""
            echo -e "${GREEN}All tools are installed!${NC}"
        else
            show_manual_instructions
        fi
    fi
}

# RTL-SDR udev rules (Linux only)
setup_udev_rules() {
    if [[ "$OS" != "macos" ]] && [[ "$OS" != "unknown" ]]; then
        echo ""
        echo -e "${BLUE}RTL-SDR udev rules (Linux only):${NC}"
        echo ""
        echo "If your RTL-SDR is not detected, you may need to add udev rules:"
        echo ""
        echo "sudo bash -c 'cat > /etc/udev/rules.d/20-rtlsdr.rules << EOF"
        echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", MODE="0666"'
        echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2832", MODE="0666"'
        echo "EOF'"
        echo ""
        echo "sudo udevadm control --reload-rules"
        echo "sudo udevadm trigger"
        echo ""
        echo "Then unplug and replug your RTL-SDR device."
    fi
}

# Main
main() {
    detect_os
    setup_sudo
    install_python_deps
    check_tools
    install_or_show_instructions

    # Show udev rules instructions for non-Debian Linux (Debian handles it automatically)
    if [[ "$OS" != "debian" ]]; then
        setup_udev_rules
    fi

    echo ""
    echo "============================================"
    echo -e "${GREEN}Setup complete!${NC}"
    echo ""
    echo "To start INTERCEPT:"
    if [ -d "venv" ]; then
        echo "  source venv/bin/activate"
        if [ -n "$SUDO" ]; then
            echo "  sudo venv/bin/python intercept.py"
        else
            echo "  venv/bin/python intercept.py"
        fi
    else
        if [ -n "$SUDO" ]; then
            echo "  sudo python3 intercept.py"
        else
            echo "  python3 intercept.py"
        fi
    fi
    echo ""
    echo "Then open http://localhost:5050 in your browser"
    echo ""
}

main "$@"
