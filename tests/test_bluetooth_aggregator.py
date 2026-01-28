"""Unit tests for Bluetooth device aggregation."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from utils.bluetooth.aggregator import DeviceAggregator
from utils.bluetooth.models import BTObservation, BTDeviceAggregate
from utils.bluetooth.constants import (
    MAX_RSSI_SAMPLES,
    DEVICE_STALE_TIMEOUT as DEVICE_STALE_SECONDS,
)


@pytest.fixture
def aggregator():
    """Create a fresh DeviceAggregator for testing."""
    return DeviceAggregator()


@pytest.fixture
def sample_observation():
    """Create a sample BLE observation."""
    return BTObservation(
        timestamp=datetime.now(),
        address="AA:BB:CC:DD:EE:FF",
        address_type="public",
        rssi=-55,
        tx_power=None,
        name="Test Device",
        manufacturer_id=76,  # Apple
        manufacturer_data=None,
        service_uuids=["0000180f-0000-1000-8000-00805f9b34fb"],
        service_data={},
        appearance=None,
        is_connectable=True,
        is_paired=False,
        is_connected=False,
        class_of_device=None,
        major_class=None,
        minor_class=None,
    )


class TestDeviceAggregator:
    """Tests for DeviceAggregator class."""

    def test_ingest_single_observation(self, aggregator, sample_observation):
        """Test ingesting a single observation creates device aggregate."""
        aggregator.ingest(sample_observation)

        devices = aggregator.get_all_devices()
        assert len(devices) == 1

        device = devices[0]
        assert device.address == "AA:BB:CC:DD:EE:FF"
        assert device.name == "Test Device"
        assert device.rssi_current == -55
        assert device.seen_count == 1

    def test_ingest_multiple_observations_same_device(self, aggregator, sample_observation):
        """Test multiple observations for same device aggregate correctly."""
        # Ingest multiple observations with varying RSSI
        rssi_values = [-55, -60, -50, -58, -52]

        for rssi in rssi_values:
            obs = BTObservation(
                timestamp=datetime.now(),
                address=sample_observation.address,
                address_type=sample_observation.address_type,
                rssi=rssi,
                tx_power=None,
                name=sample_observation.name,
                manufacturer_id=sample_observation.manufacturer_id,
                manufacturer_data=None,
                service_uuids=sample_observation.service_uuids,
                service_data={},
                appearance=None,
                is_connectable=True,
                is_paired=False,
                is_connected=False,
                class_of_device=None,
                major_class=None,
                minor_class=None,
            )
            aggregator.ingest(obs)

        devices = aggregator.get_all_devices()
        assert len(devices) == 1

        device = devices[0]
        assert device.seen_count == 5
        assert device.rssi_current == rssi_values[-1]
        assert len(device.rssi_samples) == 5

        # Check RSSI stats
        assert device.rssi_min == -60
        assert device.rssi_max == -50

    def test_rssi_median_calculation(self, aggregator, sample_observation):
        """Test RSSI median is calculated correctly."""
        rssi_values = [-70, -60, -50, -55, -65]  # Sorted: -70, -65, -60, -55, -50 -> median -60

        for rssi in rssi_values:
            obs = BTObservation(
                timestamp=datetime.now(),
                address=sample_observation.address,
                address_type="public",
                rssi=rssi,
                tx_power=None,
                name="Test",
                manufacturer_id=None,
                manufacturer_data=None,
                service_uuids=[],
                service_data={},
                appearance=None,
                is_connectable=True,
                is_paired=False,
                is_connected=False,
                class_of_device=None,
                major_class=None,
                minor_class=None,
            )
            aggregator.ingest(obs)

        device = aggregator.get_all_devices()[0]
        assert device.rssi_median == -60.0

    def test_rssi_samples_limited(self, aggregator, sample_observation):
        """Test RSSI samples are limited to MAX_RSSI_SAMPLES."""
        for i in range(MAX_RSSI_SAMPLES + 50):
            obs = BTObservation(
                timestamp=datetime.now(),
                address=sample_observation.address,
                address_type="public",
                rssi=-50 - (i % 30),
                tx_power=None,
                name="Test",
                manufacturer_id=None,
                manufacturer_data=None,
                service_uuids=[],
                service_data={},
                appearance=None,
                is_connectable=True,
                is_paired=False,
                is_connected=False,
                class_of_device=None,
                major_class=None,
                minor_class=None,
            )
            aggregator.ingest(obs)

        device = aggregator.get_all_devices()[0]
        assert len(device.rssi_samples) <= MAX_RSSI_SAMPLES

    def test_protocol_detection_ble(self, aggregator):
        """Test BLE protocol detection."""
        obs = BTObservation(
            timestamp=datetime.now(),
            address="AA:BB:CC:DD:EE:FF",
            address_type="random",  # Random address indicates BLE
            rssi=-60,
            tx_power=-8,
            name="BLE Device",
            manufacturer_id=None,
            manufacturer_data=None,
            service_uuids=["0000180a-0000-1000-8000-00805f9b34fb"],
            service_data={},
            appearance=None,
            is_connectable=True,
            is_paired=False,
            is_connected=False,
            class_of_device=None,
            major_class=None,
            minor_class=None,
        )
        aggregator.ingest(obs)

        device = aggregator.get_all_devices()[0]
        assert device.protocol == "ble"

    def test_protocol_detection_classic(self, aggregator):
        """Test Classic Bluetooth protocol detection."""
        obs = BTObservation(
            timestamp=datetime.now(),
            address="AA:BB:CC:DD:EE:FF",
            address_type="public",
            rssi=-60,
            tx_power=None,
            name="Classic Device",
            manufacturer_id=None,
            manufacturer_data=None,
            service_uuids=[],
            service_data={},
            appearance=None,
            is_connectable=True,
            is_paired=False,
            is_connected=False,
            class_of_device=0x240404,  # Audio device
            major_class="audio_video",
            minor_class="headphones",
        )
        aggregator.ingest(obs)

        device = aggregator.get_all_devices()[0]
        assert device.protocol == "classic"


class TestRangeBandEstimation:
    """Tests for range band estimation."""

    def test_range_band_very_close(self, aggregator):
        """Test very close range band detection."""
        obs = BTObservation(
            timestamp=datetime.now(),
            address="AA:BB:CC:DD:EE:FF",
            address_type="public",
            rssi=-35,  # Very strong signal
            tx_power=None,
            name="Close Device",
            manufacturer_id=None,
            manufacturer_data=None,
            service_uuids=[],
            service_data={},
            appearance=None,
            is_connectable=True,
            is_paired=False,
            is_connected=False,
            class_of_device=None,
            major_class=None,
            minor_class=None,
        )

        # Add multiple samples to build confidence
        for _ in range(10):
            aggregator.ingest(obs)

        device = aggregator.get_all_devices()[0]
        assert device.range_band == "very_close"

    def test_range_band_close(self, aggregator):
        """Test close range band detection."""
        for rssi in [-45, -48, -50, -47, -49]:
            obs = BTObservation(
                timestamp=datetime.now(),
                address="AA:BB:CC:DD:EE:FF",
                address_type="public",
                rssi=rssi,
                tx_power=None,
                name="Close Device",
                manufacturer_id=None,
                manufacturer_data=None,
                service_uuids=[],
                service_data={},
                appearance=None,
                is_connectable=True,
                is_paired=False,
                is_connected=False,
                class_of_device=None,
                major_class=None,
                minor_class=None,
            )
            aggregator.ingest(obs)

        device = aggregator.get_all_devices()[0]
        assert device.range_band in ["very_close", "close"]

    def test_range_band_far(self, aggregator):
        """Test far range band detection."""
        for rssi in [-75, -78, -80, -77, -79]:
            obs = BTObservation(
                timestamp=datetime.now(),
                address="AA:BB:CC:DD:EE:FF",
                address_type="public",
                rssi=rssi,
                tx_power=None,
                name="Far Device",
                manufacturer_id=None,
                manufacturer_data=None,
                service_uuids=[],
                service_data={},
                appearance=None,
                is_connectable=True,
                is_paired=False,
                is_connected=False,
                class_of_device=None,
                major_class=None,
                minor_class=None,
            )
            aggregator.ingest(obs)

        device = aggregator.get_all_devices()[0]
        assert device.range_band in ["nearby", "far"]

    def test_range_band_unknown_low_confidence(self, aggregator):
        """Test unknown range band with insufficient data."""
        obs = BTObservation(
            timestamp=datetime.now(),
            address="AA:BB:CC:DD:EE:FF",
            address_type="public",
            rssi=-60,
            tx_power=None,
            name="Unknown Device",
            manufacturer_id=None,
            manufacturer_data=None,
            service_uuids=[],
            service_data={},
            appearance=None,
            is_connectable=True,
            is_paired=False,
            is_connected=False,
            class_of_device=None,
            major_class=None,
            minor_class=None,
        )
        aggregator.ingest(obs)

        device = aggregator.get_all_devices()[0]
        # With only one sample, confidence is low
        assert device.rssi_confidence < 0.5


class TestBaselineManagement:
    """Tests for baseline functionality."""

    def test_set_baseline(self, aggregator, sample_observation):
        """Test setting a baseline from current devices."""
        aggregator.ingest(sample_observation)
        count = aggregator.set_baseline()

        assert count == 1
        assert aggregator.has_baseline()

    def test_clear_baseline(self, aggregator, sample_observation):
        """Test clearing the baseline."""
        aggregator.ingest(sample_observation)
        aggregator.set_baseline()
        aggregator.clear_baseline()

        assert not aggregator.has_baseline()

    def test_is_new_device(self, aggregator, sample_observation):
        """Test detection of new devices vs baseline."""
        # Add first device and set baseline
        aggregator.ingest(sample_observation)
        aggregator.set_baseline()

        # Add new device
        new_obs = BTObservation(
            timestamp=datetime.now(),
            address="11:22:33:44:55:66",
            address_type="public",
            rssi=-60,
            tx_power=None,
            name="New Device",
            manufacturer_id=None,
            manufacturer_data=None,
            service_uuids=[],
            service_data={},
            appearance=None,
            is_connectable=True,
            is_paired=False,
            is_connected=False,
            class_of_device=None,
            major_class=None,
            minor_class=None,
        )
        aggregator.ingest(new_obs)

        devices = aggregator.get_all_devices()
        new_device = next(d for d in devices if d.address == "11:22:33:44:55:66")

        assert new_device.is_new is True

        # Original device should not be new
        original = next(d for d in devices if d.address == sample_observation.address)
        assert original.is_new is False


class TestDevicePruning:
    """Tests for stale device pruning."""

    def test_prune_stale_devices(self, aggregator):
        """Test that stale devices are removed."""
        # Create an old observation
        old_time = datetime.now() - timedelta(seconds=DEVICE_STALE_SECONDS + 60)
        old_obs = BTObservation(
            timestamp=old_time,
            address="AA:BB:CC:DD:EE:FF",
            address_type="public",
            rssi=-60,
            tx_power=None,
            name="Old Device",
            manufacturer_id=None,
            manufacturer_data=None,
            service_uuids=[],
            service_data={},
            appearance=None,
            is_connectable=True,
            is_paired=False,
            is_connected=False,
            class_of_device=None,
            major_class=None,
            minor_class=None,
        )
        aggregator.ingest(old_obs)

        # Create a recent observation for different device
        recent_obs = BTObservation(
            timestamp=datetime.now(),
            address="11:22:33:44:55:66",
            address_type="public",
            rssi=-55,
            tx_power=None,
            name="Recent Device",
            manufacturer_id=None,
            manufacturer_data=None,
            service_uuids=[],
            service_data={},
            appearance=None,
            is_connectable=True,
            is_paired=False,
            is_connected=False,
            class_of_device=None,
            major_class=None,
            minor_class=None,
        )
        aggregator.ingest(recent_obs)

        # Prune stale devices
        pruned = aggregator.prune_stale()

        assert pruned == 1
        devices = aggregator.get_all_devices()
        assert len(devices) == 1
        assert devices[0].address == "11:22:33:44:55:66"


class TestDeviceFiltering:
    """Tests for device filtering and sorting."""

    def test_filter_by_protocol(self, aggregator):
        """Test filtering devices by protocol."""
        # Add BLE device
        ble_obs = BTObservation(
            timestamp=datetime.now(),
            address="AA:BB:CC:DD:EE:FF",
            address_type="random",
            rssi=-60,
            tx_power=-8,
            name="BLE Device",
            manufacturer_id=None,
            manufacturer_data=None,
            service_uuids=["0000180a-0000-1000-8000-00805f9b34fb"],
            service_data={},
            appearance=None,
            is_connectable=True,
            is_paired=False,
            is_connected=False,
            class_of_device=None,
            major_class=None,
            minor_class=None,
        )
        aggregator.ingest(ble_obs)

        # Add Classic device
        classic_obs = BTObservation(
            timestamp=datetime.now(),
            address="11:22:33:44:55:66",
            address_type="public",
            rssi=-55,
            tx_power=None,
            name="Classic Device",
            manufacturer_id=None,
            manufacturer_data=None,
            service_uuids=[],
            service_data={},
            appearance=None,
            is_connectable=True,
            is_paired=False,
            is_connected=False,
            class_of_device=0x240404,
            major_class="audio_video",
            minor_class=None,
        )
        aggregator.ingest(classic_obs)

        # Filter by BLE
        ble_devices = aggregator.get_all_devices(protocol="ble")
        assert len(ble_devices) == 1
        assert ble_devices[0].protocol == "ble"

        # Filter by Classic
        classic_devices = aggregator.get_all_devices(protocol="classic")
        assert len(classic_devices) == 1
        assert classic_devices[0].protocol == "classic"

    def test_filter_by_min_rssi(self, aggregator):
        """Test filtering devices by minimum RSSI."""
        for i, rssi in enumerate([-50, -70, -90]):
            obs = BTObservation(
                timestamp=datetime.now(),
                address=f"AA:BB:CC:DD:EE:{i:02X}",
                address_type="public",
                rssi=rssi,
                tx_power=None,
                name=f"Device {i}",
                manufacturer_id=None,
                manufacturer_data=None,
                service_uuids=[],
                service_data={},
                appearance=None,
                is_connectable=True,
                is_paired=False,
                is_connected=False,
                class_of_device=None,
                major_class=None,
                minor_class=None,
            )
            aggregator.ingest(obs)

        # Filter by min RSSI -60
        strong_devices = aggregator.get_all_devices(min_rssi=-60)
        assert len(strong_devices) == 1
        assert strong_devices[0].rssi_current == -50

    def test_sort_by_rssi(self, aggregator):
        """Test sorting devices by RSSI."""
        for rssi in [-70, -50, -90, -60]:
            obs = BTObservation(
                timestamp=datetime.now(),
                address=f"AA:BB:CC:DD:{abs(rssi):02X}:FF",
                address_type="public",
                rssi=rssi,
                tx_power=None,
                name=f"Device RSSI {rssi}",
                manufacturer_id=None,
                manufacturer_data=None,
                service_uuids=[],
                service_data={},
                appearance=None,
                is_connectable=True,
                is_paired=False,
                is_connected=False,
                class_of_device=None,
                major_class=None,
                minor_class=None,
            )
            aggregator.ingest(obs)

        # Sort by RSSI (strongest first)
        devices = aggregator.get_all_devices(sort_by="rssi")
        rssi_values = [d.rssi_current for d in devices]
        assert rssi_values == [-50, -60, -70, -90]
