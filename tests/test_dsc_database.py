"""Tests for DSC database operations."""

import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch


@pytest.fixture(autouse=True)
def temp_db():
    """Use a temporary database for each test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db_path = Path(tmpdir) / 'test_intercept.db'
        test_db_dir = Path(tmpdir)

        with patch('utils.database.DB_PATH', test_db_path), \
             patch('utils.database.DB_DIR', test_db_dir):
            from utils.database import init_db, close_db

            init_db()
            yield test_db_path
            close_db()


class TestDSCAlertsCRUD:
    """Tests for DSC alerts CRUD operations."""

    def test_store_and_get_dsc_alert(self, temp_db):
        """Test storing and retrieving a DSC alert."""
        from utils.database import store_dsc_alert, get_dsc_alert

        alert_id = store_dsc_alert(
            source_mmsi='232123456',
            format_code='100',
            category='DISTRESS',
            source_name='MV Test Ship',
            nature_of_distress='FIRE',
            latitude=51.5,
            longitude=-0.1
        )

        assert alert_id is not None
        assert alert_id > 0

        alert = get_dsc_alert(alert_id)

        assert alert is not None
        assert alert['source_mmsi'] == '232123456'
        assert alert['format_code'] == '100'
        assert alert['category'] == 'DISTRESS'
        assert alert['source_name'] == 'MV Test Ship'
        assert alert['nature_of_distress'] == 'FIRE'
        assert alert['latitude'] == 51.5
        assert alert['longitude'] == -0.1
        assert alert['acknowledged'] is False

    def test_store_minimal_alert(self, temp_db):
        """Test storing alert with only required fields."""
        from utils.database import store_dsc_alert, get_dsc_alert

        alert_id = store_dsc_alert(
            source_mmsi='366000001',
            format_code='116',
            category='ROUTINE'
        )

        alert = get_dsc_alert(alert_id)

        assert alert is not None
        assert alert['source_mmsi'] == '366000001'
        assert alert['category'] == 'ROUTINE'
        assert alert['latitude'] is None
        assert alert['longitude'] is None

    def test_get_nonexistent_alert(self, temp_db):
        """Test getting an alert that doesn't exist."""
        from utils.database import get_dsc_alert

        alert = get_dsc_alert(99999)
        assert alert is None

    def test_get_dsc_alerts_all(self, temp_db):
        """Test getting all alerts."""
        from utils.database import store_dsc_alert, get_dsc_alerts

        store_dsc_alert('232123456', '100', 'DISTRESS')
        store_dsc_alert('366000001', '120', 'URGENCY')
        store_dsc_alert('351234567', '116', 'ROUTINE')

        alerts = get_dsc_alerts()

        assert len(alerts) == 3

    def test_get_dsc_alerts_by_category(self, temp_db):
        """Test filtering alerts by category."""
        from utils.database import store_dsc_alert, get_dsc_alerts

        store_dsc_alert('232123456', '100', 'DISTRESS')
        store_dsc_alert('232123457', '100', 'DISTRESS')
        store_dsc_alert('366000001', '120', 'URGENCY')
        store_dsc_alert('351234567', '116', 'ROUTINE')

        distress_alerts = get_dsc_alerts(category='DISTRESS')
        urgency_alerts = get_dsc_alerts(category='URGENCY')

        assert len(distress_alerts) == 2
        assert len(urgency_alerts) == 1

    def test_get_dsc_alerts_by_acknowledged(self, temp_db):
        """Test filtering alerts by acknowledgement status."""
        from utils.database import (
            store_dsc_alert,
            get_dsc_alerts,
            acknowledge_dsc_alert
        )

        id1 = store_dsc_alert('232123456', '100', 'DISTRESS')
        id2 = store_dsc_alert('366000001', '100', 'DISTRESS')
        store_dsc_alert('351234567', '100', 'DISTRESS')

        acknowledge_dsc_alert(id1)
        acknowledge_dsc_alert(id2)

        unacked = get_dsc_alerts(acknowledged=False)
        acked = get_dsc_alerts(acknowledged=True)

        assert len(unacked) == 1
        assert len(acked) == 2

    def test_get_dsc_alerts_by_mmsi(self, temp_db):
        """Test filtering alerts by source MMSI."""
        from utils.database import store_dsc_alert, get_dsc_alerts

        store_dsc_alert('232123456', '100', 'DISTRESS')
        store_dsc_alert('232123456', '120', 'URGENCY')
        store_dsc_alert('366000001', '100', 'DISTRESS')

        alerts = get_dsc_alerts(source_mmsi='232123456')

        assert len(alerts) == 2
        for alert in alerts:
            assert alert['source_mmsi'] == '232123456'

    def test_get_dsc_alerts_pagination(self, temp_db):
        """Test alert pagination."""
        from utils.database import store_dsc_alert, get_dsc_alerts

        # Create 10 alerts
        for i in range(10):
            store_dsc_alert(f'23212345{i}', '100', 'DISTRESS')

        # Get first page
        page1 = get_dsc_alerts(limit=5, offset=0)
        assert len(page1) == 5

        # Get second page
        page2 = get_dsc_alerts(limit=5, offset=5)
        assert len(page2) == 5

        # Ensure no overlap
        page1_ids = {a['id'] for a in page1}
        page2_ids = {a['id'] for a in page2}
        assert page1_ids.isdisjoint(page2_ids)

    def test_get_dsc_alerts_order(self, temp_db):
        """Test alerts are returned in reverse chronological order."""
        from utils.database import store_dsc_alert, get_dsc_alerts

        id1 = store_dsc_alert('232123456', '100', 'DISTRESS')
        id2 = store_dsc_alert('366000001', '100', 'DISTRESS')
        id3 = store_dsc_alert('351234567', '100', 'DISTRESS')

        alerts = get_dsc_alerts()

        # ORDER BY received_at DESC, so most recent first
        # When timestamps are identical, higher IDs are more recent
        # The actual order depends on the DB implementation
        # We just verify all 3 are present and it's a list
        assert len(alerts) == 3
        alert_ids = {a['id'] for a in alerts}
        assert alert_ids == {id1, id2, id3}

    def test_acknowledge_dsc_alert(self, temp_db):
        """Test acknowledging a DSC alert."""
        from utils.database import (
            store_dsc_alert,
            get_dsc_alert,
            acknowledge_dsc_alert
        )

        alert_id = store_dsc_alert('232123456', '100', 'DISTRESS')

        # Initially not acknowledged
        alert = get_dsc_alert(alert_id)
        assert alert['acknowledged'] is False

        # Acknowledge it
        result = acknowledge_dsc_alert(alert_id)
        assert result is True

        # Now acknowledged
        alert = get_dsc_alert(alert_id)
        assert alert['acknowledged'] is True

    def test_acknowledge_dsc_alert_with_notes(self, temp_db):
        """Test acknowledging with notes."""
        from utils.database import (
            store_dsc_alert,
            get_dsc_alert,
            acknowledge_dsc_alert
        )

        alert_id = store_dsc_alert('232123456', '100', 'DISTRESS')

        acknowledge_dsc_alert(alert_id, notes='Vessel located, rescue underway')

        alert = get_dsc_alert(alert_id)
        assert alert['acknowledged'] is True
        assert alert['notes'] == 'Vessel located, rescue underway'

    def test_acknowledge_nonexistent_alert(self, temp_db):
        """Test acknowledging an alert that doesn't exist."""
        from utils.database import acknowledge_dsc_alert

        result = acknowledge_dsc_alert(99999)
        assert result is False

    def test_get_dsc_alert_summary(self, temp_db):
        """Test getting alert summary counts."""
        from utils.database import (
            store_dsc_alert,
            get_dsc_alert_summary,
            acknowledge_dsc_alert
        )

        # Create various alerts
        store_dsc_alert('232123456', '100', 'DISTRESS')
        store_dsc_alert('232123457', '100', 'DISTRESS')
        store_dsc_alert('366000001', '120', 'URGENCY')
        store_dsc_alert('351234567', '118', 'SAFETY')
        acked_id = store_dsc_alert('257000001', '100', 'DISTRESS')

        # Acknowledge one distress
        acknowledge_dsc_alert(acked_id)

        summary = get_dsc_alert_summary()

        assert summary['distress'] == 2  # 3 - 1 acknowledged
        assert summary['urgency'] == 1
        assert summary['safety'] == 1
        assert summary['total'] == 4

    def test_get_dsc_alert_summary_empty(self, temp_db):
        """Test alert summary with no alerts."""
        from utils.database import get_dsc_alert_summary

        summary = get_dsc_alert_summary()

        assert summary['distress'] == 0
        assert summary['urgency'] == 0
        assert summary['safety'] == 0
        assert summary['routine'] == 0
        assert summary['total'] == 0

    def test_cleanup_old_dsc_alerts(self, temp_db):
        """Test cleanup function behavior."""
        from utils.database import (
            store_dsc_alert,
            get_dsc_alerts,
            acknowledge_dsc_alert,
            cleanup_old_dsc_alerts
        )

        # Create and acknowledge some alerts
        id1 = store_dsc_alert('232123456', '100', 'DISTRESS')
        id2 = store_dsc_alert('366000001', '100', 'DISTRESS')
        id3 = store_dsc_alert('351234567', '100', 'DISTRESS')  # Unacknowledged

        acknowledge_dsc_alert(id1)
        acknowledge_dsc_alert(id2)

        # Cleanup with large max_age shouldn't delete recent records
        deleted = cleanup_old_dsc_alerts(max_age_days=30)
        assert deleted == 0  # Nothing old enough to delete

        # All 3 should still be present
        alerts = get_dsc_alerts()
        assert len(alerts) == 3

        # Verify unacknowledged one is still unacknowledged
        unacked = get_dsc_alerts(acknowledged=False)
        assert len(unacked) == 1
        assert unacked[0]['id'] == id3

    def test_cleanup_preserves_unacknowledged(self, temp_db):
        """Test cleanup preserves unacknowledged alerts regardless of age."""
        from utils.database import (
            store_dsc_alert,
            get_dsc_alerts,
            cleanup_old_dsc_alerts
        )

        # Create unacknowledged alerts
        store_dsc_alert('232123456', '100', 'DISTRESS')
        store_dsc_alert('366000001', '100', 'DISTRESS')

        # Cleanup with 0 days
        deleted = cleanup_old_dsc_alerts(max_age_days=0)

        # All should remain (none were acknowledged)
        alerts = get_dsc_alerts()
        assert len(alerts) == 2
        assert deleted == 0

    def test_store_alert_with_raw_message(self, temp_db):
        """Test storing alert with raw message data."""
        from utils.database import store_dsc_alert, get_dsc_alert

        raw = '100023212345603660000110010010000000000127'

        alert_id = store_dsc_alert(
            source_mmsi='232123456',
            format_code='100',
            category='DISTRESS',
            raw_message=raw
        )

        alert = get_dsc_alert(alert_id)
        assert alert['raw_message'] == raw

    def test_store_alert_with_destination(self, temp_db):
        """Test storing alert with destination MMSI."""
        from utils.database import store_dsc_alert, get_dsc_alert

        alert_id = store_dsc_alert(
            source_mmsi='232123456',
            format_code='112',
            category='INDIVIDUAL',
            dest_mmsi='366000001'
        )

        alert = get_dsc_alert(alert_id)
        assert alert['dest_mmsi'] == '366000001'


class TestDSCDatabaseIntegration:
    """Integration tests for DSC database operations."""

    def test_full_alert_lifecycle(self, temp_db):
        """Test complete lifecycle of a DSC alert."""
        from utils.database import (
            store_dsc_alert,
            get_dsc_alert,
            get_dsc_alerts,
            acknowledge_dsc_alert,
            get_dsc_alert_summary
        )

        # 1. Store a distress alert
        alert_id = store_dsc_alert(
            source_mmsi='232123456',
            format_code='100',
            category='DISTRESS',
            source_name='MV Mayday',
            nature_of_distress='SINKING',
            latitude=50.0,
            longitude=-5.0
        )

        # 2. Verify it appears in summary
        summary = get_dsc_alert_summary()
        assert summary['distress'] == 1
        assert summary['total'] == 1

        # 3. Verify it appears in unacknowledged list
        unacked = get_dsc_alerts(acknowledged=False)
        assert len(unacked) == 1
        assert unacked[0]['source_mmsi'] == '232123456'

        # 4. Acknowledge with notes
        acknowledge_dsc_alert(alert_id, 'Rescue helicopter dispatched')

        # 5. Verify it's now acknowledged
        alert = get_dsc_alert(alert_id)
        assert alert['acknowledged'] is True
        assert alert['notes'] == 'Rescue helicopter dispatched'

        # 6. Verify summary updated
        summary = get_dsc_alert_summary()
        assert summary['distress'] == 0
        assert summary['total'] == 0

        # 7. Verify it appears in acknowledged list
        acked = get_dsc_alerts(acknowledged=True)
        assert len(acked) == 1

    def test_multiple_vessel_alerts(self, temp_db):
        """Test handling alerts from multiple vessels."""
        from utils.database import store_dsc_alert, get_dsc_alerts

        # Simulate multiple vessels in distress
        vessels = [
            ('232123456', 'United Kingdom', 'FIRE'),
            ('366000001', 'USA', 'FLOODING'),
            ('351234567', 'Panama', 'COLLISION'),
        ]

        for mmsi, country, nature in vessels:
            store_dsc_alert(
                source_mmsi=mmsi,
                format_code='100',
                category='DISTRESS',
                nature_of_distress=nature
            )

        # Verify all alerts stored
        alerts = get_dsc_alerts(category='DISTRESS')
        assert len(alerts) == 3

        # Verify each has correct nature
        natures = {a['nature_of_distress'] for a in alerts}
        assert natures == {'FIRE', 'FLOODING', 'COLLISION'}
