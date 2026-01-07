#!/usr/bin/env bash
# INTERCEPT Setup Script (best-effort installs, hard-fail verification)

# ---- Force bash even if launched with sh ----
if [ -z "${BASH_VERSION:-}" ]; then
  echo "[x] This script must be run with bash (not sh)."
  echo "    Run: bash $0"
  exec bash "$0" "$@"
fi

set -Eeuo pipefail

# Ensure admin paths are searchable (many tools live here)
export PATH="/usr/local/sbin:/usr/sbin:/sbin:/opt/homebrew/sbin:/opt/homebrew/bin:$PATH"

# ----------------------------
# Pretty output
# ----------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[*]${NC} $*"; }
ok()    { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
fail()  { echo -e "${RED}[x]${NC} $*"; }

on_error() {
  local line="$1"
  local cmd="${2:-unknown}"
  fail "Setup failed at line ${line}: ${cmd}"
  exit 1
}
trap 'on_error $LINENO "$BASH_COMMAND"' ERR

# ----------------------------
# Banner
# ----------------------------
echo -e "${BLUE}"
echo "  ___ _   _ _____ _____ ____   ____ _____ ____ _____ "
echo " |_ _| \\ | |_   _| ____|  _ \\ / ___| ____|  _ \\_   _|"
echo "  | ||  \\| | | | |  _| | |_) | |   |  _| | |_) || |  "
echo "  | || |\\  | | | | |___|  _ <| |___| |___|  __/ | |  "
echo " |___|_| \\_| |_| |_____|_| \\_\\\\____|_____|_|    |_|  "
echo -e "${NC}"
echo "INTERCEPT - Setup Script"
echo "============================================"
echo

# ----------------------------
# Helpers
# ----------------------------
cmd_exists() {
  local c="$1"
  command -v "$c" >/dev/null 2>&1 && return 0
  [[ -x "/usr/sbin/$c" || -x "/sbin/$c" || -x "/usr/local/sbin/$c" || -x "/opt/homebrew/sbin/$c" ]] && return 0
  return 1
}

have_any() {
  local c
  for c in "$@"; do
    cmd_exists "$c" && return 0
  done
  return 1
}

need_sudo() {
  if [[ "$(id -u)" -eq 0 ]]; then
    SUDO=""
    ok "Running as root"
  else
    if cmd_exists sudo; then
      SUDO="sudo"
    else
      fail "sudo is not installed and you're not root."
      echo "Either run as root or install sudo first."
      exit 1
    fi
  fi
}

detect_os() {
  if [[ "${OSTYPE:-}" == "darwin"* ]]; then
    OS="macos"
  elif [[ -f /etc/debian_version ]]; then
    OS="debian"
  else
    OS="unknown"
  fi
  info "Detected OS: ${OS}"
  [[ "$OS" != "unknown" ]] || { fail "Unsupported OS (macOS + Debian/Ubuntu only)."; exit 1; }
}

# ----------------------------
# Required tool checks (with alternates)
# ----------------------------
missing_required=()

check_required() {
  local label="$1"; shift
  local desc="$1"; shift

  if have_any "$@"; then
    ok "${label} - ${desc}"
  else
    warn "${label} - ${desc} (missing, required)"
    missing_required+=("$label")
  fi
}

check_tools() {
  info "Checking required tools..."
  missing_required=()

  echo
  info "Core SDR:"
  check_required "rtl_fm"      "RTL-SDR FM demodulator" rtl_fm
  check_required "rtl_test"    "RTL-SDR device detection" rtl_test
  check_required "multimon-ng" "Pager decoder" multimon-ng
  check_required "rtl_433"     "433MHz sensor decoder" rtl_433 rtl433
  check_required "dump1090"    "ADS-B decoder" dump1090

  echo
  info "Audio:"
  check_required "ffmpeg" "Audio encoder/decoder" ffmpeg

  echo
  info "WiFi:"
  check_required "airmon-ng"     "Monitor mode helper" airmon-ng
  check_required "airodump-ng"   "WiFi scanner" airodump-ng
  check_required "aireplay-ng"   "Injection/deauth" aireplay-ng
  check_required "hcxdumptool"   "PMKID capture" hcxdumptool
  check_required "hcxpcapngtool" "PMKID/pcapng conversion" hcxpcapngtool

  echo
  info "Bluetooth:"
  check_required "bluetoothctl" "Bluetooth controller CLI" bluetoothctl
  check_required "hcitool"      "Bluetooth scan utility" hcitool
  check_required "hciconfig"    "Bluetooth adapter config" hciconfig

  echo
  info "SoapySDR:"
  check_required "SoapySDRUtil" "SoapySDR CLI utility" SoapySDRUtil
  echo
}

# ----------------------------
# Python venv + deps
# ----------------------------
check_python_version() {
  if ! cmd_exists python3; then
    fail "python3 not found."
    [[ "$OS" == "macos" ]] && echo "Install with: brew install python"
    [[ "$OS" == "debian" ]] && echo "Install with: sudo apt-get install python3"
    exit 1
  fi

  local ver
  ver="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  info "Python version: ${ver}"

  python3 - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3,9) else 1)
PY
  ok "Python version OK (>= 3.9)"
}

install_python_deps() {
  info "Setting up Python virtual environment..."
  check_python_version

  if [[ ! -f requirements.txt ]]; then
    warn "requirements.txt not found; skipping Python dependency install."
    return 0
  fi

  if [[ ! -d venv ]]; then
    python3 -m venv venv
    ok "Created venv/"
  else
    ok "Using existing venv/"
  fi

  # shellcheck disable=SC1091
  source venv/bin/activate

  python -m pip install --upgrade pip setuptools wheel >/dev/null
  ok "Upgraded pip tooling"

  info "Installing Python requirements..."
  python -m pip install -r requirements.txt
  ok "Python dependencies installed"
  echo
}

# ----------------------------
# macOS install (Homebrew)
# ----------------------------
ensure_brew() {
  cmd_exists brew && return 0
  warn "Homebrew not found. Installing Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

  if [[ -x /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -x /usr/local/bin/brew ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi

  cmd_exists brew || { fail "Homebrew install failed. Install manually then re-run."; exit 1; }
}

brew_install() {
  local pkg="$1"
  if brew list --formula "$pkg" >/dev/null 2>&1; then
    ok "brew: ${pkg} already installed"
    return 0
  fi
  info "brew: installing ${pkg}..."
  brew install "$pkg"
  ok "brew: installed ${pkg}"
}

install_macos_packages() {
  ensure_brew
  info "Installing packages via Homebrew..."

  brew_install librtlsdr
  brew_install multimon-ng
  brew_install ffmpeg
  brew_install rtl_433

  # ADS-B (may not exist)
  warn "Attempting dump1090 install via Homebrew (may be unavailable)..."
  (brew_install dump1090-mutability) || true

  brew_install aircrack-ng
  brew_install hcxtools
  brew_install soapysdr

  warn "macOS note: hcitool/hciconfig are Linux (BlueZ) utilities and often unavailable on macOS."
  echo
}

# ----------------------------
# Debian/Ubuntu install (APT)
# ----------------------------
apt_install() { $SUDO apt-get install -y --no-install-recommends "$@" >/dev/null; }

apt_try_install_any() {
  local p
  for p in "$@"; do
    if $SUDO apt-get install -y --no-install-recommends "$p" >/dev/null 2>&1; then
      ok "apt: installed ${p}"
      return 0
    fi
  done
  return 1
}

install_dump1090_from_source_debian() {
  info "dump1090 not available via APT. Building from source (required)..."

  apt_install build-essential git pkg-config \
    librtlsdr-dev libusb-1.0-0-dev \
    libncurses-dev tcl-dev python3-dev

  local orig_dir tmp_dir
  orig_dir="$(pwd)"
  tmp_dir="$(mktemp -d)"

  cleanup() { cd "$orig_dir" >/dev/null 2>&1 || true; rm -rf "$tmp_dir"; }
  trap cleanup EXIT

  info "Cloning FlightAware dump1090..."
  git clone --depth 1 https://github.com/flightaware/dump1090.git "$tmp_dir/dump1090" >/dev/null 2>&1 \
    || { fail "Failed to clone FlightAware dump1090"; exit 1; }

  cd "$tmp_dir/dump1090"
  info "Compiling FlightAware dump1090..."
  if make BLADERF=no RTLSDR=yes >/dev/null 2>&1; then
    $SUDO install -m 0755 dump1090 /usr/local/bin/dump1090
    ok "dump1090 installed successfully (FlightAware)."
    return 0
  fi

  warn "FlightAware build failed. Falling back to antirez/dump1090..."
  rm -rf "$tmp_dir/dump1090"
  git clone --depth 1 https://github.com/antirez/dump1090.git "$tmp_dir/dump1090" >/dev/null 2>&1 \
    || { fail "Failed to clone antirez dump1090"; exit 1; }

  cd "$tmp_dir/dump1090"
  info "Compiling antirez dump1090..."
  make >/dev/null 2>&1 || { fail "Failed to build dump1090 from source (required)."; exit 1; }

  $SUDO install -m 0755 dump1090 /usr/local/bin/dump1090
  ok "dump1090 installed successfully (antirez)."
}

setup_udev_rules_debian() {
  [[ -d /etc/udev/rules.d ]] || { warn "udev not found; skipping RTL-SDR udev rules."; return 0; }

  local rules_file="/etc/udev/rules.d/20-rtlsdr.rules"
  [[ -f "$rules_file" ]] && { ok "RTL-SDR udev rules already present: $rules_file"; return 0; }

  info "Installing RTL-SDR udev rules..."
  $SUDO tee "$rules_file" >/dev/null <<'EOF'
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", MODE="0666"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2832", MODE="0666"
EOF
  $SUDO udevadm control --reload-rules || true
  $SUDO udevadm trigger || true
  ok "udev rules installed. Unplug/replug your RTL-SDR if connected."
  echo
}

install_debian_packages() {
  need_sudo
  info "Updating APT package lists..."
  $SUDO apt-get update -y >/dev/null

  info "Installing required packages via APT..."
  apt_install rtl-sdr
  apt_install multimon-ng
  apt_install ffmpeg

  apt_try_install_any rtl-433 rtl433 || true

  apt_install aircrack-ng || true
  apt_install hcxdumptool || true
  apt_install hcxtools || true
  apt_install bluez bluetooth || true
  apt_install soapysdr-tools || true

  # dump1090: apt first; source fallback; hard fail inside if it can't build
  if ! cmd_exists dump1090; then
    apt_try_install_any dump1090-fa dump1090-mutability dump1090 || true
  fi
  cmd_exists dump1090 || install_dump1090_from_source_debian

  setup_udev_rules_debian
}

# ----------------------------
# Final summary / hard fail
# ----------------------------
final_summary_and_hard_fail() {
  check_tools

  echo "============================================"
  if [[ "${#missing_required[@]}" -eq 0 ]]; then
    ok "All REQUIRED tools are installed."
  else
    fail "Missing REQUIRED tools:"
    for t in "${missing_required[@]}"; do echo "  - $t"; done
    echo
    fail "Exiting because required tools are missing."
    echo
    warn "If you are on macOS: hcitool/hciconfig are Linux (BlueZ) tools and may not be installable."
    warn "If you truly require them everywhere, you must restrict supported platforms or provide alternatives."
    exit 1
  fi

  echo
  echo "To start INTERCEPT:"
  echo "  source venv/bin/activate"
  echo "  sudo python intercept.py"
  echo
  echo "Then open http://localhost:5050 in your browser"
  echo
}

# ----------------------------
# MAIN
# ----------------------------
main() {
  detect_os

  if [[ "$OS" == "macos" ]]; then
    install_macos_packages
  else
    install_debian_packages
  fi

  install_python_deps
  final_summary_and_hard_fail
}

main "$@"

