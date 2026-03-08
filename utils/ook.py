"""Generic OOK (On-Off Keying) signal decoder utilities.

Decodes raw OOK frames captured by rtl_433's flex decoder.  The flex
decoder handles pulse-width to bit mapping for PWM, PPM, and Manchester
schemes; this layer receives the resulting hex bytes and extracts the
raw bit string so the browser can perform live ASCII interpretation with
configurable bit order.

Supported modulation schemes (via rtl_433 flex decoder):
  - OOK_PWM       : Pulse Width Modulation (short=0, long=1)
  - OOK_PPM       : Pulse Position Modulation (short gap=0, long gap=1)
  - OOK_MC_ZEROBIT: Manchester encoding (zero-bit start)

Usage with rtl_433:
  rtl_433 -f 433500000 -R 0 \\
    -X "n=ook,m=OOK_PWM,s=500,l=1500,r=8000,g=5000,t=150,bits>=8" -F json
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from datetime import datetime
from typing import Any

logger = logging.getLogger('intercept.ook')


def decode_ook_frame(hex_data: str) -> dict[str, Any] | None:
    """Decode an OOK frame from a hex string produced by rtl_433.

    rtl_433's flex decoder already translates pulse timing into bits and
    packs them into bytes.  This function unpacks those bytes into an
    explicit bit string (MSB first) so the browser can re-interpret the
    same bits with either byte order on the fly.

    Args:
        hex_data: Hex string from the rtl_433 ``codes`` / ``code`` /
            ``data`` field, e.g. ``"aa55b248656c6c6f"``.

    Returns:
        Dict with ``bits`` (MSB-first bit string), ``hex`` (clean hex),
        ``byte_count``, and ``bit_count``, or ``None`` on parse failure.
    """
    try:
        cleaned = hex_data.replace(' ', '')
        # rtl_433 flex decoder prefixes hex with '0x' — strip it
        if cleaned.startswith(('0x', '0X')):
            cleaned = cleaned[2:]
        raw = bytes.fromhex(cleaned)
    except ValueError:
        return None

    if not raw:
        return None

    # Expand bytes to MSB-first bit string
    bits = ''.join(f'{b:08b}' for b in raw)

    return {
        'bits': bits,
        'hex': raw.hex(),
        'byte_count': len(raw),
        'bit_count': len(bits),
    }


def ook_parser_thread(
    rtl_stdout,
    output_queue: queue.Queue,
    stop_event: threading.Event,
    encoding: str = 'pwm',
    deduplicate: bool = False,
) -> None:
    """Thread function: reads rtl_433 JSON output and emits OOK frame events.

    Handles the three rtl_433 hex-output field names (``codes``, ``code``,
    ``data``).  Emits a ``status: stopped`` event when the parser exits
    (normal EOF or unexpected crash) so the frontend can update its UI.

    Args:
        rtl_stdout: rtl_433 stdout pipe.
        output_queue: Queue for SSE events.
        stop_event: Threading event to signal shutdown.
        encoding: Modulation hint (``'pwm'``, ``'ppm'``, ``'manchester'``).
            Informational only — rtl_433 already decoded the bits.
        deduplicate: If True, consecutive frames with identical hex are
            suppressed; only the first is emitted.

    Events emitted:
      type='ook_frame'  — decoded frame with bits and hex
      type='ook_raw'    — raw rtl_433 JSON that contained no code field
      type='status'     — start/stop notifications
      type='error'      — error messages
    """
    last_hex: str | None = None

    try:
        for line in iter(rtl_stdout.readline, b''):
            if stop_event.is_set():
                break

            text = line.decode('utf-8', errors='replace').strip()
            if not text:
                continue

            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                logger.debug(f'[rtl_433/ook] {text}')
                continue

            # rtl_433 flex decoder puts hex in 'codes' (list or string),
            # 'code' (singular), or 'data' depending on version.
            codes = data.get('codes')
            if codes is not None:
                if isinstance(codes, str):
                    codes = [codes] if codes else None

            if not codes:
                code = data.get('code')
                if code:
                    codes = [str(code)]

            if not codes:
                raw_data = data.get('data')
                if raw_data:
                    codes = [str(raw_data)]

            # Extract signal level if rtl_433 was invoked with -M level
            rssi: float | None = None
            for _rssi_key in ('snr', 'rssi', 'level', 'noise'):
                _rssi_val = data.get(_rssi_key)
                if _rssi_val is not None:
                    try:
                        rssi = round(float(_rssi_val), 1)
                    except (TypeError, ValueError):
                        pass
                    break

            if not codes:
                logger.warning(
                    f'[rtl_433/ook] no code field — keys: {list(data.keys())}'
                )
                try:
                    output_queue.put_nowait({
                        'type': 'ook_raw',
                        'data': data,
                        'timestamp': datetime.now().strftime('%H:%M:%S'),
                    })
                except queue.Full:
                    pass
                continue

            for code_hex in codes:
                hex_str = str(code_hex).strip()
                # Strip leading {N} bit-count prefix if present
                if hex_str.startswith('{'):
                    brace_end = hex_str.find('}')
                    if brace_end >= 0:
                        hex_str = hex_str[brace_end + 1:]

                frame = decode_ook_frame(hex_str)
                if frame is None:
                    continue

                timestamp = datetime.now().strftime('%H:%M:%S')

                # Deduplication: skip if identical to last frame
                is_dup = deduplicate and frame['hex'] == last_hex
                last_hex = frame['hex']

                if deduplicate and is_dup:
                    continue

                try:
                    event: dict[str, Any] = {
                        'type': 'ook_frame',
                        'hex': frame['hex'],
                        'bits': frame['bits'],
                        'byte_count': frame['byte_count'],
                        'bit_count': frame['bit_count'],
                        'inverted': False,
                        'encoding': encoding,
                        'timestamp': timestamp,
                    }
                    if rssi is not None:
                        event['rssi'] = rssi
                    output_queue.put_nowait(event)
                except queue.Full:
                    pass

    except Exception as e:
        logger.warning(f'OOK parser thread error: {e}')
        try:
            output_queue.put_nowait({'type': 'error', 'text': str(e)})
        except queue.Full:
            pass

    # Notify frontend that the parser has stopped (covers both normal exit
    # and unexpected rtl_433 crashes so the UI doesn't stay in "Listening").
    try:
        output_queue.put_nowait({'type': 'status', 'text': 'stopped'})
    except queue.Full:
        pass
