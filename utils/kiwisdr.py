"""KiwiSDR WebSocket audio client.

Connects to a KiwiSDR receiver via its WebSocket API and streams
decoded PCM audio back through a callback.
"""

from __future__ import annotations

import struct
import threading
import time
from typing import Optional, Callable

try:
    import websocket  # websocket-client library
    WEBSOCKET_CLIENT_AVAILABLE = True
except ImportError:
    WEBSOCKET_CLIENT_AVAILABLE = False

from utils.logging import get_logger

logger = get_logger('intercept.kiwisdr')

# Protocol constants
KIWI_KEEPALIVE_INTERVAL = 5.0
KIWI_SAMPLE_RATE = 12000  # 12 kHz mono
KIWI_SND_HEADER_SIZE = 10  # "SND"(3) + flags(1) + seq(4) + smeter(2)
KIWI_DEFAULT_PORT = 8073

VALID_MODES = ('am', 'usb', 'lsb', 'cw')

# Default bandpass filters per mode (Hz)
MODE_FILTERS = {
    'am': (-4500, 4500),
    'usb': (300, 3000),
    'lsb': (-3000, -300),
    'cw': (300, 800),
}


def parse_host_port(url: str) -> tuple[str, int]:
    """Extract host and port from a KiwiSDR URL like 'http://host:port'.

    Returns (host, port) tuple. Defaults to port 8073 if not specified.
    """
    if not url:
        return ('', KIWI_DEFAULT_PORT)

    # Strip protocol
    cleaned = url
    for prefix in ('http://', 'https://', 'ws://', 'wss://'):
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break

    # Strip path
    cleaned = cleaned.split('/')[0]

    # Split host:port
    if ':' in cleaned:
        parts = cleaned.rsplit(':', 1)
        host = parts[0]
        try:
            port = int(parts[1])
        except ValueError:
            port = KIWI_DEFAULT_PORT
    else:
        host = cleaned
        port = KIWI_DEFAULT_PORT

    return (host, port)


class KiwiSDRClient:
    """Manages a WebSocket connection to a single KiwiSDR receiver."""

    def __init__(
        self,
        host: str,
        port: int = KIWI_DEFAULT_PORT,
        on_audio: Optional[Callable[[bytes, int], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_disconnect: Optional[Callable[[], None]] = None,
        password: str = '',
    ):
        self.host = host
        self.port = port
        self.password = password
        self._on_audio = on_audio
        self._on_error = on_error
        self._on_disconnect = on_disconnect

        self._ws = None
        self._connected = False
        self._stopping = False
        self._receive_thread: Optional[threading.Thread] = None
        self._keepalive_thread: Optional[threading.Thread] = None
        self._send_lock = threading.Lock()

        self.frequency_khz: float = 0
        self.mode: str = 'am'
        self.last_smeter: int = 0

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self, frequency_khz: float, mode: str = 'am') -> bool:
        """Connect to KiwiSDR and start receiving audio."""
        if not WEBSOCKET_CLIENT_AVAILABLE:
            logger.error("websocket-client not installed")
            return False

        if self._connected:
            self.disconnect()

        self.frequency_khz = frequency_khz
        self.mode = mode if mode in VALID_MODES else 'am'
        self._stopping = False

        ws_url = self._build_ws_url()
        logger.info(f"Connecting to KiwiSDR: {ws_url}")

        try:
            self._ws = websocket.WebSocket()
            self._ws.settimeout(10)
            self._ws.connect(ws_url)

            # Auth
            self._send('SET auth t=kiwi p=' + self.password)
            time.sleep(0.2)

            # Request uncompressed PCM
            self._send('SET compression=0')

            # Set AGC
            self._send('SET agc=1 hang=0 thresh=-100 slope=6 decay=1000 manGain=50')

            # Tune to frequency
            self._send_tune(frequency_khz, self.mode)

            # Request audio start
            self._send('SET AR OK in=12000 out=44100')

            self._connected = True

            # Start receive thread
            self._receive_thread = threading.Thread(
                target=self._receive_loop, daemon=True, name='kiwi-rx'
            )
            self._receive_thread.start()

            # Start keepalive thread
            self._keepalive_thread = threading.Thread(
                target=self._keepalive_loop, daemon=True, name='kiwi-ka'
            )
            self._keepalive_thread.start()

            logger.info(f"Connected to KiwiSDR {self.host}:{self.port} @ {frequency_khz} kHz {self.mode}")
            return True

        except Exception as e:
            logger.error(f"KiwiSDR connection failed: {e}")
            self._cleanup()
            return False

    def tune(self, frequency_khz: float, mode: str = 'am') -> bool:
        """Retune without disconnecting."""
        if not self._connected or not self._ws:
            return False

        self.frequency_khz = frequency_khz
        if mode in VALID_MODES:
            self.mode = mode

        try:
            self._send_tune(frequency_khz, self.mode)
            logger.info(f"Retuned to {frequency_khz} kHz {self.mode}")
            return True
        except Exception as e:
            logger.error(f"Retune failed: {e}")
            return False

    def disconnect(self) -> None:
        """Cleanly disconnect from KiwiSDR."""
        self._stopping = True
        self._connected = False
        self._cleanup()
        logger.info("Disconnected from KiwiSDR")

    def _build_ws_url(self) -> str:
        ts = int(time.time() * 1000)
        return f'ws://{self.host}:{self.port}/{ts}/SND'

    def _send(self, msg: str) -> None:
        with self._send_lock:
            if self._ws:
                self._ws.send(msg)

    def _send_tune(self, freq_khz: float, mode: str) -> None:
        low_cut, high_cut = MODE_FILTERS.get(mode, MODE_FILTERS['am'])
        self._send(f'SET mod={mode} low_cut={low_cut} high_cut={high_cut} freq={freq_khz}')

    def _receive_loop(self) -> None:
        """Background thread: read frames from KiwiSDR WebSocket."""
        try:
            while self._connected and not self._stopping:
                try:
                    if not self._ws:
                        break
                    self._ws.settimeout(2.0)
                    data = self._ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                except Exception as e:
                    if not self._stopping:
                        logger.error(f"KiwiSDR receive error: {e}")
                    break

                if not data or not isinstance(data, bytes):
                    # Text message (status/config) — ignore
                    continue

                self._parse_snd_frame(data)

        except Exception as e:
            if not self._stopping:
                logger.error(f"KiwiSDR receive loop error: {e}")
        finally:
            if not self._stopping:
                self._connected = False
                if self._on_disconnect:
                    try:
                        self._on_disconnect()
                    except Exception:
                        pass

    def _parse_snd_frame(self, data: bytes) -> None:
        """Parse a KiwiSDR SND binary frame."""
        if len(data) < KIWI_SND_HEADER_SIZE:
            return

        # Check header magic
        if data[:3] != b'SND':
            return

        # flags = data[3]
        # seq = struct.unpack('>I', data[4:8])[0]

        # S-meter: big-endian int16 at offset 8
        smeter_raw = struct.unpack('>h', data[8:10])[0]
        self.last_smeter = smeter_raw

        # PCM audio data starts at offset 10
        pcm_data = data[KIWI_SND_HEADER_SIZE:]

        if pcm_data and self._on_audio:
            try:
                self._on_audio(pcm_data, smeter_raw)
            except Exception:
                pass

    def _keepalive_loop(self) -> None:
        """Background thread: send keepalive every 5 seconds."""
        while self._connected and not self._stopping:
            time.sleep(KIWI_KEEPALIVE_INTERVAL)
            if self._connected and not self._stopping:
                try:
                    self._send('SET keepalive')
                except Exception:
                    break

    def _cleanup(self) -> None:
        """Close WebSocket and join threads."""
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

        if self._receive_thread and self._receive_thread.is_alive():
            self._receive_thread.join(timeout=3.0)
        if self._keepalive_thread and self._keepalive_thread.is_alive():
            self._keepalive_thread.join(timeout=3.0)

        self._receive_thread = None
        self._keepalive_thread = None
