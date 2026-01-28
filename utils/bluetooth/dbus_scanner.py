"""
DBus-based BlueZ scanner for Bluetooth device discovery.

Uses org.bluez signals for real-time device discovery.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Callable, Optional

from .constants import (
    BLUEZ_SERVICE,
    BLUEZ_PATH,
    BLUEZ_ADAPTER_INTERFACE,
    BLUEZ_DEVICE_INTERFACE,
    DBUS_PROPERTIES_INTERFACE,
    DBUS_OBJECT_MANAGER_INTERFACE,
    DISCOVERY_FILTER_TRANSPORT,
    DISCOVERY_FILTER_RSSI,
    DISCOVERY_FILTER_DUPLICATE_DATA,
    ADDRESS_TYPE_PUBLIC,
    ADDRESS_TYPE_RANDOM,
    MAJOR_DEVICE_CLASSES,
    MINOR_AUDIO_VIDEO,
    MINOR_PHONE,
    MINOR_COMPUTER,
    MINOR_PERIPHERAL,
    MINOR_WEARABLE,
)
from .models import BTObservation

logger = logging.getLogger(__name__)


class DBusScanner:
    """
    BlueZ DBus-based Bluetooth scanner.

    Subscribes to BlueZ signals for real-time device discovery without polling.
    """

    def __init__(
        self,
        adapter_path: Optional[str] = None,
        on_observation: Optional[Callable[[BTObservation], None]] = None,
    ):
        """
        Initialize DBus scanner.

        Args:
            adapter_path: DBus path to adapter (e.g., '/org/bluez/hci0').
            on_observation: Callback for new observations.
        """
        self._adapter_path = adapter_path
        self._on_observation = on_observation
        self._bus = None
        self._adapter = None
        self._mainloop = None
        self._mainloop_thread: Optional[threading.Thread] = None
        self._is_scanning = False
        self._lock = threading.Lock()
        self._known_devices: set[str] = set()

    def start(self, transport: str = 'auto', rssi_threshold: int = -100) -> bool:
        """
        Start DBus discovery.

        Args:
            transport: Discovery transport ('bredr', 'le', or 'auto').
            rssi_threshold: Minimum RSSI for discovered devices.

        Returns:
            True if started successfully, False otherwise.
        """
        try:
            import dbus
            from dbus.mainloop.glib import DBusGMainLoop
            from gi.repository import GLib

            with self._lock:
                if self._is_scanning:
                    return True

                # Set up DBus mainloop
                DBusGMainLoop(set_as_default=True)
                self._bus = dbus.SystemBus()

                # Get adapter
                if not self._adapter_path:
                    self._adapter_path = self._find_default_adapter()

                if not self._adapter_path:
                    logger.error("No Bluetooth adapter found")
                    return False

                adapter_obj = self._bus.get_object(BLUEZ_SERVICE, self._adapter_path)
                self._adapter = dbus.Interface(adapter_obj, BLUEZ_ADAPTER_INTERFACE)
                adapter_props = dbus.Interface(adapter_obj, DBUS_PROPERTIES_INTERFACE)

                # Set up signal handlers
                self._bus.add_signal_receiver(
                    self._on_interfaces_added,
                    signal_name='InterfacesAdded',
                    dbus_interface=DBUS_OBJECT_MANAGER_INTERFACE,
                    bus_name=BLUEZ_SERVICE,
                )

                self._bus.add_signal_receiver(
                    self._on_properties_changed,
                    signal_name='PropertiesChanged',
                    dbus_interface=DBUS_PROPERTIES_INTERFACE,
                    path_keyword='path',
                )

                # Set discovery filter
                try:
                    filter_dict = {
                        'Transport': dbus.String(transport if transport != 'auto' else 'auto'),
                        'DuplicateData': dbus.Boolean(DISCOVERY_FILTER_DUPLICATE_DATA),
                    }
                    if rssi_threshold > -100:
                        filter_dict['RSSI'] = dbus.Int16(rssi_threshold)

                    self._adapter.SetDiscoveryFilter(filter_dict)
                except dbus.exceptions.DBusException as e:
                    logger.warning(f"Failed to set discovery filter: {e}")

                # Start discovery
                try:
                    self._adapter.StartDiscovery()
                except dbus.exceptions.DBusException as e:
                    if 'InProgress' not in str(e):
                        logger.error(f"Failed to start discovery: {e}")
                        return False

                # Process existing devices
                self._process_existing_devices()

                # Start mainloop in background thread
                self._mainloop = GLib.MainLoop()
                self._mainloop_thread = threading.Thread(
                    target=self._run_mainloop,
                    daemon=True
                )
                self._mainloop_thread.start()

                self._is_scanning = True
                logger.info(f"DBus scanner started on {self._adapter_path}")
                return True

        except ImportError as e:
            logger.error(f"Missing DBus dependencies: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to start DBus scanner: {e}")
            return False

    def stop(self) -> None:
        """Stop DBus discovery."""
        with self._lock:
            if not self._is_scanning:
                return

            try:
                if self._adapter:
                    try:
                        self._adapter.StopDiscovery()
                    except Exception as e:
                        logger.debug(f"StopDiscovery error (expected): {e}")

                if self._mainloop and self._mainloop.is_running():
                    self._mainloop.quit()

                if self._mainloop_thread:
                    self._mainloop_thread.join(timeout=2.0)

            except Exception as e:
                logger.error(f"Error stopping DBus scanner: {e}")
            finally:
                self._is_scanning = False
                self._adapter = None
                self._bus = None
                self._mainloop = None
                self._mainloop_thread = None
                logger.info("DBus scanner stopped")

    @property
    def is_scanning(self) -> bool:
        """Check if scanner is active."""
        with self._lock:
            return self._is_scanning

    def _run_mainloop(self) -> None:
        """Run the GLib mainloop."""
        try:
            self._mainloop.run()
        except Exception as e:
            logger.error(f"Mainloop error: {e}")

    def _find_default_adapter(self) -> Optional[str]:
        """Find the default Bluetooth adapter via DBus."""
        try:
            import dbus
            manager = dbus.Interface(
                self._bus.get_object(BLUEZ_SERVICE, '/'),
                DBUS_OBJECT_MANAGER_INTERFACE
            )

            objects = manager.GetManagedObjects()
            for path, interfaces in objects.items():
                if BLUEZ_ADAPTER_INTERFACE in interfaces:
                    return str(path)
            return None
        except Exception as e:
            logger.error(f"Failed to find adapter: {e}")
            return None

    def _process_existing_devices(self) -> None:
        """Process devices that already exist in BlueZ."""
        try:
            import dbus
            manager = dbus.Interface(
                self._bus.get_object(BLUEZ_SERVICE, '/'),
                DBUS_OBJECT_MANAGER_INTERFACE
            )

            objects = manager.GetManagedObjects()
            for path, interfaces in objects.items():
                if BLUEZ_DEVICE_INTERFACE in interfaces:
                    props = interfaces[BLUEZ_DEVICE_INTERFACE]
                    self._process_device_properties(str(path), props)

        except Exception as e:
            logger.error(f"Failed to process existing devices: {e}")

    def _on_interfaces_added(self, path: str, interfaces: dict) -> None:
        """Handle InterfacesAdded signal (new device discovered)."""
        if BLUEZ_DEVICE_INTERFACE in interfaces:
            props = interfaces[BLUEZ_DEVICE_INTERFACE]
            self._process_device_properties(str(path), props)

    def _on_properties_changed(
        self,
        interface: str,
        changed: dict,
        invalidated: list,
        path: str = None
    ) -> None:
        """Handle PropertiesChanged signal (device properties updated)."""
        if interface != BLUEZ_DEVICE_INTERFACE:
            return

        if path and '/dev_' in path:
            try:
                import dbus
                device_obj = self._bus.get_object(BLUEZ_SERVICE, path)
                props_iface = dbus.Interface(device_obj, DBUS_PROPERTIES_INTERFACE)
                all_props = props_iface.GetAll(BLUEZ_DEVICE_INTERFACE)
                self._process_device_properties(path, all_props)
            except Exception as e:
                logger.debug(f"Failed to get device properties for {path}: {e}")

    def _process_device_properties(self, path: str, props: dict) -> None:
        """Convert BlueZ device properties to BTObservation."""
        try:
            import dbus

            address = str(props.get('Address', ''))
            if not address:
                return

            # Determine address type
            address_type = ADDRESS_TYPE_PUBLIC
            addr_type_raw = props.get('AddressType', 'public')
            if addr_type_raw:
                addr_type_str = str(addr_type_raw).lower()
                if 'random' in addr_type_str:
                    address_type = ADDRESS_TYPE_RANDOM

            # Extract name
            name = None
            if 'Name' in props:
                name = str(props['Name'])
            elif 'Alias' in props and props['Alias'] != address:
                name = str(props['Alias'])

            # Extract RSSI
            rssi = None
            if 'RSSI' in props:
                rssi = int(props['RSSI'])

            # Extract TX Power
            tx_power = None
            if 'TxPower' in props:
                tx_power = int(props['TxPower'])

            # Extract manufacturer data
            manufacturer_id = None
            manufacturer_data = None
            if 'ManufacturerData' in props:
                mfr_data = props['ManufacturerData']
                if mfr_data:
                    for mid, mdata in mfr_data.items():
                        manufacturer_id = int(mid)
                        # Handle various DBus data types safely
                        try:
                            if isinstance(mdata, (bytes, bytearray)):
                                manufacturer_data = bytes(mdata)
                            elif isinstance(mdata, dbus.Array):
                                manufacturer_data = bytes(mdata)
                            elif isinstance(mdata, (list, tuple)):
                                manufacturer_data = bytes(mdata)
                            elif isinstance(mdata, str):
                                manufacturer_data = bytes.fromhex(mdata)
                        except (TypeError, ValueError) as e:
                            logger.debug(f"Could not convert manufacturer data: {e}")
                        break

            # Extract service UUIDs
            service_uuids = []
            if 'UUIDs' in props:
                for uuid in props['UUIDs']:
                    service_uuids.append(str(uuid))

            # Extract service data
            service_data = {}
            if 'ServiceData' in props:
                for uuid, data in props['ServiceData'].items():
                    try:
                        if isinstance(data, (bytes, bytearray)):
                            service_data[str(uuid)] = bytes(data)
                        elif isinstance(data, dbus.Array):
                            service_data[str(uuid)] = bytes(data)
                        elif isinstance(data, (list, tuple)):
                            service_data[str(uuid)] = bytes(data)
                        elif isinstance(data, str):
                            service_data[str(uuid)] = bytes.fromhex(data)
                    except (TypeError, ValueError) as e:
                        logger.debug(f"Could not convert service data for {uuid}: {e}")

            # Extract Class of Device (Classic BT)
            class_of_device = None
            major_class = None
            minor_class = None
            if 'Class' in props:
                class_of_device = int(props['Class'])
                major_class, minor_class = self._decode_class_of_device(class_of_device)

            # Connection state
            is_connected = bool(props.get('Connected', False))
            is_paired = bool(props.get('Paired', False))

            # Appearance
            appearance = None
            if 'Appearance' in props:
                appearance = int(props['Appearance'])

            # Create observation
            observation = BTObservation(
                timestamp=datetime.now(),
                address=address.upper(),
                address_type=address_type,
                rssi=rssi,
                tx_power=tx_power,
                name=name,
                manufacturer_id=manufacturer_id,
                manufacturer_data=manufacturer_data,
                service_uuids=service_uuids,
                service_data=service_data,
                appearance=appearance,
                is_connectable=True,  # If we see it in BlueZ, it's connectable
                is_paired=is_paired,
                is_connected=is_connected,
                class_of_device=class_of_device,
                major_class=major_class,
                minor_class=minor_class,
                adapter_id=self._adapter_path,
            )

            # Callback
            if self._on_observation:
                self._on_observation(observation)

            self._known_devices.add(address)

        except Exception as e:
            logger.error(f"Failed to process device properties: {e}")

    def _decode_class_of_device(self, cod: int) -> tuple[Optional[str], Optional[str]]:
        """Decode Bluetooth Class of Device."""
        # Major class is bits 12-8 (5 bits)
        major_num = (cod >> 8) & 0x1F

        # Minor class is bits 7-2 (6 bits)
        minor_num = (cod >> 2) & 0x3F

        major_class = MAJOR_DEVICE_CLASSES.get(major_num)

        # Get minor class based on major class
        minor_class = None
        if major_num == 0x04:  # Audio/Video
            minor_class = MINOR_AUDIO_VIDEO.get(minor_num)
        elif major_num == 0x02:  # Phone
            minor_class = MINOR_PHONE.get(minor_num)
        elif major_num == 0x01:  # Computer
            minor_class = MINOR_COMPUTER.get(minor_num)
        elif major_num == 0x05:  # Peripheral
            minor_class = MINOR_PERIPHERAL.get(minor_num & 0x03)
        elif major_num == 0x07:  # Wearable
            minor_class = MINOR_WEARABLE.get(minor_num)

        return major_class, minor_class
