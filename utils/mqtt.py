"""
MQTT Client Manager for Intercept.

Provides a singleton MQTT client for publishing decoded data to an MQTT broker.
Supports automatic reconnection, thread-safe publishing, and configuration via settings.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    mqtt = None

from utils.database import get_setting, set_setting

logger = logging.getLogger('intercept.mqtt')

# Default settings
DEFAULT_BROKER_HOST = 'localhost'
DEFAULT_BROKER_PORT = 1883
DEFAULT_CLIENT_ID = 'intercept'
DEFAULT_TOPIC_PREFIX = 'intercept'
DEFAULT_QOS = 1
DEFAULT_KEEPALIVE = 60

# Reconnection settings
RECONNECT_MIN_DELAY = 1
RECONNECT_MAX_DELAY = 60
RECONNECT_MULTIPLIER = 2


class MQTTManager:
    """
    Singleton MQTT client manager.

    Handles connection, reconnection, and thread-safe publishing to MQTT broker.
    Configuration is loaded from the settings database.
    """

    _instance: Optional['MQTTManager'] = None
    _lock = threading.Lock()

    def __new__(cls) -> 'MQTTManager':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self._client: Optional[mqtt.Client] = None
        self._connected = False
        self._connecting = False
        self._publish_queue: queue.Queue = queue.Queue(maxsize=10000)
        self._publish_thread: Optional[threading.Thread] = None
        self._reconnect_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._reconnect_delay = RECONNECT_MIN_DELAY
        self._last_error: Optional[str] = None
        self._stats = {
            'messages_published': 0,
            'messages_failed': 0,
            'reconnect_attempts': 0,
            'last_publish_time': None
        }

        logger.info("MQTTManager initialized")

    @property
    def is_available(self) -> bool:
        """Check if paho-mqtt library is available."""
        return MQTT_AVAILABLE

    @property
    def is_enabled(self) -> bool:
        """Check if MQTT is enabled in settings."""
        return get_setting('mqtt_enabled', False)

    @property
    def is_connected(self) -> bool:
        """Check if currently connected to broker."""
        return self._connected and self._client is not None

    @property
    def last_error(self) -> Optional[str]:
        """Get last error message."""
        return self._last_error

    @property
    def stats(self) -> dict:
        """Get publishing statistics."""
        return self._stats.copy()

    def get_config(self) -> dict:
        """Get current MQTT configuration from settings."""
        return {
            'enabled': get_setting('mqtt_enabled', False),
            'broker_host': get_setting('mqtt_broker_host', DEFAULT_BROKER_HOST),
            'broker_port': get_setting('mqtt_broker_port', DEFAULT_BROKER_PORT),
            'username': get_setting('mqtt_username', ''),
            'password': '***' if get_setting('mqtt_password', '') else '',
            'use_tls': get_setting('mqtt_use_tls', False),
            'client_id': get_setting('mqtt_client_id', DEFAULT_CLIENT_ID),
            'topic_prefix': get_setting('mqtt_topic_prefix', DEFAULT_TOPIC_PREFIX),
            'qos': get_setting('mqtt_qos', DEFAULT_QOS),
            'topics': {
                'pocsag': get_setting('mqtt_pocsag_enabled', True),
                'adsb': get_setting('mqtt_adsb_enabled', True),
                'acars': get_setting('mqtt_acars_enabled', True),
                'aprs': get_setting('mqtt_aprs_enabled', True),
                'sensor': get_setting('mqtt_sensor_enabled', True),
                'rtlamr': get_setting('mqtt_rtlamr_enabled', True)
            }
        }

    def save_config(self, config: dict) -> bool:
        """Save MQTT configuration to settings."""
        try:
            if 'enabled' in config:
                set_setting('mqtt_enabled', config['enabled'])
            if 'broker_host' in config:
                set_setting('mqtt_broker_host', config['broker_host'])
            if 'broker_port' in config:
                set_setting('mqtt_broker_port', int(config['broker_port']))
            if 'username' in config:
                set_setting('mqtt_username', config['username'])
            if 'password' in config and config['password'] != '***':
                set_setting('mqtt_password', config['password'])
            if 'use_tls' in config:
                set_setting('mqtt_use_tls', config['use_tls'])
            if 'client_id' in config:
                set_setting('mqtt_client_id', config['client_id'])
            if 'topic_prefix' in config:
                set_setting('mqtt_topic_prefix', config['topic_prefix'])
            if 'qos' in config:
                set_setting('mqtt_qos', int(config['qos']))
            if 'topics' in config:
                topics = config['topics']
                if 'pocsag' in topics:
                    set_setting('mqtt_pocsag_enabled', topics['pocsag'])
                if 'adsb' in topics:
                    set_setting('mqtt_adsb_enabled', topics['adsb'])
                if 'acars' in topics:
                    set_setting('mqtt_acars_enabled', topics['acars'])
                if 'aprs' in topics:
                    set_setting('mqtt_aprs_enabled', topics['aprs'])
                if 'sensor' in topics:
                    set_setting('mqtt_sensor_enabled', topics['sensor'])
                if 'rtlamr' in topics:
                    set_setting('mqtt_rtlamr_enabled', topics['rtlamr'])

            logger.info("MQTT configuration saved")
            return True
        except Exception as e:
            logger.error(f"Failed to save MQTT config: {e}")
            self._last_error = str(e)
            return False

    def connect(self) -> bool:
        """
        Connect to the MQTT broker.

        Returns True if connection was initiated successfully.
        """
        if not MQTT_AVAILABLE:
            self._last_error = "paho-mqtt library not installed"
            logger.error(self._last_error)
            return False

        if self._connected or self._connecting:
            return True

        self._connecting = True
        self._stop_event.clear()

        try:
            config = self.get_config()

            # Create client
            client_id = config['client_id'] + '_' + str(int(time.time()))
            self._client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)

            # Set callbacks
            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect
            self._client.on_publish = self._on_publish

            # Authentication
            username = config['username']
            password = get_setting('mqtt_password', '')
            if username:
                self._client.username_pw_set(username, password)

            # TLS
            if config['use_tls']:
                self._client.tls_set()

            # Connect
            logger.info(f"Connecting to MQTT broker at {config['broker_host']}:{config['broker_port']}")
            self._client.connect_async(
                config['broker_host'],
                config['broker_port'],
                keepalive=DEFAULT_KEEPALIVE
            )

            # Start network loop
            self._client.loop_start()

            # Start publish thread
            self._start_publish_thread()

            return True

        except Exception as e:
            self._connecting = False
            self._last_error = str(e)
            logger.error(f"Failed to connect to MQTT broker: {e}")
            return False

    def disconnect(self) -> bool:
        """
        Disconnect from the MQTT broker.

        Returns True if disconnection was successful.
        """
        self._stop_event.set()

        if self._client:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")
            finally:
                self._client = None

        self._connected = False
        self._connecting = False

        # Wait for publish thread
        if self._publish_thread and self._publish_thread.is_alive():
            self._publish_thread.join(timeout=2)

        logger.info("Disconnected from MQTT broker")
        return True

    def publish(self, decoder_type: str, data: dict) -> bool:
        """
        Publish data to MQTT topic.

        Args:
            decoder_type: Type of decoder (pocsag, adsb, acars, aprs, sensor, rtlamr)
            data: Dictionary of data to publish

        Returns True if message was queued for publishing.
        """
        if not self.is_enabled:
            return False

        if not self._connected:
            # Try to connect if enabled but not connected
            if not self._connecting:
                self.connect()
            return False

        # Check if this decoder type is enabled
        topic_setting = f'mqtt_{decoder_type}_enabled'
        if not get_setting(topic_setting, True):
            return False

        try:
            # Add timestamp if not present
            if '@timestamp' not in data:
                data['@timestamp'] = datetime.now(timezone.utc).isoformat()

            # Add decoder type
            data['decoder'] = decoder_type

            # Build topic
            prefix = get_setting('mqtt_topic_prefix', DEFAULT_TOPIC_PREFIX)
            topic = f"{prefix}/{decoder_type}"

            # Queue message
            message = {
                'topic': topic,
                'payload': json.dumps(data, default=str),
                'qos': get_setting('mqtt_qos', DEFAULT_QOS)
            }

            self._publish_queue.put_nowait(message)
            return True

        except queue.Full:
            self._stats['messages_failed'] += 1
            logger.warning("MQTT publish queue full, dropping message")
            return False
        except Exception as e:
            self._stats['messages_failed'] += 1
            logger.error(f"Failed to queue MQTT message: {e}")
            return False

    def test_connection(self) -> dict:
        """
        Test connection to MQTT broker.

        Returns dict with success status and message.
        """
        if not MQTT_AVAILABLE:
            return {'success': False, 'message': 'paho-mqtt library not installed'}

        config = self.get_config()
        test_client = None

        try:
            client_id = 'intercept_test_' + str(int(time.time()))
            test_client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)

            # Authentication
            username = config['username']
            password = get_setting('mqtt_password', '')
            if username:
                test_client.username_pw_set(username, password)

            # TLS
            if config['use_tls']:
                test_client.tls_set()

            # Connect with timeout
            test_client.connect(
                config['broker_host'],
                config['broker_port'],
                keepalive=10
            )

            # Quick test publish
            prefix = config['topic_prefix']
            result = test_client.publish(f"{prefix}/test", '{"test": true}', qos=0)
            result.wait_for_publish(timeout=5)

            test_client.disconnect()

            return {
                'success': True,
                'message': f"Successfully connected to {config['broker_host']}:{config['broker_port']}"
            }

        except Exception as e:
            return {'success': False, 'message': str(e)}
        finally:
            if test_client:
                try:
                    test_client.disconnect()
                except Exception:
                    pass

    def _on_connect(self, client, userdata, flags, rc):
        """Callback when connected to broker."""
        if rc == 0:
            self._connected = True
            self._connecting = False
            self._reconnect_delay = RECONNECT_MIN_DELAY
            self._last_error = None
            logger.info("Connected to MQTT broker")
        else:
            self._connected = False
            self._connecting = False
            error_messages = {
                1: "Incorrect protocol version",
                2: "Invalid client identifier",
                3: "Server unavailable",
                4: "Bad username or password",
                5: "Not authorized"
            }
            self._last_error = error_messages.get(rc, f"Unknown error (code {rc})")
            logger.error(f"MQTT connection failed: {self._last_error}")

    def _on_disconnect(self, client, userdata, rc):
        """Callback when disconnected from broker."""
        self._connected = False

        if rc != 0:
            self._last_error = f"Unexpected disconnection (code {rc})"
            logger.warning(f"MQTT disconnected unexpectedly: {self._last_error}")

            # Start reconnection if enabled and not stopping
            if self.is_enabled and not self._stop_event.is_set():
                self._start_reconnect_thread()
        else:
            logger.info("MQTT disconnected gracefully")

    def _on_publish(self, client, userdata, mid):
        """Callback when message is published."""
        self._stats['messages_published'] += 1
        self._stats['last_publish_time'] = datetime.now(timezone.utc).isoformat()

    def _start_publish_thread(self):
        """Start the background publish thread."""
        if self._publish_thread and self._publish_thread.is_alive():
            return

        self._publish_thread = threading.Thread(target=self._publish_loop, daemon=True)
        self._publish_thread.start()

    def _publish_loop(self):
        """Background thread for publishing queued messages."""
        while not self._stop_event.is_set():
            try:
                message = self._publish_queue.get(timeout=1)

                if self._connected and self._client:
                    result = self._client.publish(
                        message['topic'],
                        message['payload'],
                        qos=message['qos']
                    )

                    if result.rc != mqtt.MQTT_ERR_SUCCESS:
                        self._stats['messages_failed'] += 1
                        logger.warning(f"MQTT publish failed: {result.rc}")
                else:
                    # Re-queue if not connected
                    try:
                        self._publish_queue.put_nowait(message)
                    except queue.Full:
                        self._stats['messages_failed'] += 1
                    time.sleep(0.1)

            except queue.Empty:
                continue
            except Exception as e:
                self._stats['messages_failed'] += 1
                logger.error(f"Error in publish loop: {e}")

    def _start_reconnect_thread(self):
        """Start background reconnection thread."""
        if self._reconnect_thread and self._reconnect_thread.is_alive():
            return

        self._reconnect_thread = threading.Thread(target=self._reconnect_loop, daemon=True)
        self._reconnect_thread.start()

    def _reconnect_loop(self):
        """Background thread for reconnection with exponential backoff."""
        while not self._stop_event.is_set() and self.is_enabled and not self._connected:
            self._stats['reconnect_attempts'] += 1
            logger.info(f"Attempting MQTT reconnection (delay: {self._reconnect_delay}s)")

            time.sleep(self._reconnect_delay)

            if self._stop_event.is_set():
                break

            try:
                if self._client:
                    self._client.reconnect()
                else:
                    self.connect()

            except Exception as e:
                logger.warning(f"MQTT reconnection failed: {e}")
                self._reconnect_delay = min(
                    self._reconnect_delay * RECONNECT_MULTIPLIER,
                    RECONNECT_MAX_DELAY
                )

    def shutdown(self):
        """Shutdown the MQTT manager."""
        logger.info("Shutting down MQTT manager")
        self.disconnect()

        # Clear queue
        while not self._publish_queue.empty():
            try:
                self._publish_queue.get_nowait()
            except queue.Empty:
                break


# Global instance
_mqtt_manager: Optional[MQTTManager] = None


def get_mqtt_manager() -> MQTTManager:
    """Get the global MQTT manager instance."""
    global _mqtt_manager
    if _mqtt_manager is None:
        _mqtt_manager = MQTTManager()
    return _mqtt_manager


def mqtt_publish(decoder_type: str, data: dict) -> bool:
    """
    Convenience function to publish data via MQTT.

    Args:
        decoder_type: Type of decoder (pocsag, adsb, acars, aprs, sensor, rtlamr)
        data: Dictionary of data to publish

    Returns True if message was queued for publishing.
    """
    manager = get_mqtt_manager()
    return manager.publish(decoder_type, data)
