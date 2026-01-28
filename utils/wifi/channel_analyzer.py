"""
WiFi channel utilization analysis and recommendations.

Analyzes channel congestion based on:
- Number of access points per channel
- Number of clients per channel
- Signal strength (stronger = more interference)
- Channel overlap effects
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .constants import (
    BAND_2_4_GHZ,
    BAND_5_GHZ,
    BAND_6_GHZ,
    CHANNELS_2_4_GHZ,
    CHANNELS_5_GHZ,
    CHANNELS_6_GHZ,
    NON_OVERLAPPING_2_4_GHZ,
    NON_OVERLAPPING_5_GHZ,
    CHANNEL_FREQUENCIES,
    CHANNEL_WEIGHT_AP_COUNT,
    CHANNEL_WEIGHT_CLIENT_COUNT,
    CHANNEL_RSSI_INTERFERENCE_FACTOR,
    get_band_from_channel,
)
from .models import WiFiAccessPoint, ChannelStats, ChannelRecommendation

logger = logging.getLogger(__name__)


# DFS channels (Dynamic Frequency Selection) - require radar detection
DFS_CHANNELS_5_GHZ = list(range(52, 65)) + list(range(100, 145))


@dataclass
class ChannelScore:
    """Internal scoring for a channel."""
    channel: int
    band: str
    ap_count: int = 0
    client_count: int = 0
    rssi_sum: float = 0.0
    rssi_count: int = 0
    overlap_penalty: float = 0.0


class ChannelAnalyzer:
    """
    Analyzes WiFi channel utilization and provides recommendations.

    Uses a scoring algorithm that considers:
    1. AP density (60% weight by default)
    2. Client density (40% weight by default)
    3. Signal strength adjustment (stronger signals = more interference)
    4. Channel overlap effects for 2.4 GHz
    """

    def __init__(
        self,
        ap_weight: float = CHANNEL_WEIGHT_AP_COUNT,
        client_weight: float = CHANNEL_WEIGHT_CLIENT_COUNT,
        rssi_factor: float = CHANNEL_RSSI_INTERFERENCE_FACTOR,
    ):
        """
        Initialize channel analyzer.

        Args:
            ap_weight: Weight for AP count in utilization score (0-1).
            client_weight: Weight for client count in utilization score (0-1).
            rssi_factor: Factor for RSSI-based interference adjustment.
        """
        self.ap_weight = ap_weight
        self.client_weight = client_weight
        self.rssi_factor = rssi_factor

    def analyze(
        self,
        access_points: list[WiFiAccessPoint],
        include_dfs: bool = False,
    ) -> tuple[list[ChannelStats], list[ChannelRecommendation]]:
        """
        Analyze channel utilization from access point data.

        Args:
            access_points: List of discovered access points.
            include_dfs: Whether to include DFS channels in recommendations.

        Returns:
            Tuple of (channel_stats, recommendations).
        """
        # Build per-channel scores
        scores: dict[int, ChannelScore] = {}

        for ap in access_points:
            if ap.channel is None:
                continue

            channel = ap.channel
            if channel not in scores:
                scores[channel] = ChannelScore(
                    channel=channel,
                    band=get_band_from_channel(channel),
                )

            score = scores[channel]
            score.ap_count += 1
            score.client_count += ap.client_count

            if ap.rssi_current is not None:
                score.rssi_sum += ap.rssi_current
                score.rssi_count += 1

        # Calculate overlap penalties for 2.4 GHz
        self._calculate_overlap_penalties(scores)

        # Convert to ChannelStats
        channel_stats = self._build_channel_stats(scores)

        # Generate recommendations
        recommendations = self._generate_recommendations(
            scores, access_points, include_dfs
        )

        return channel_stats, recommendations

    def _calculate_overlap_penalties(self, scores: dict[int, ChannelScore]):
        """Calculate overlap penalties for 2.4 GHz channels."""
        # In 2.4 GHz, channels overlap: each channel is 22 MHz wide
        # but only 5 MHz apart. Channels 1, 6, 11 don't overlap.
        #
        # Channel overlap:
        # - Adjacent channel (+/- 1): 75% overlap
        # - 2 channels apart: 50% overlap
        # - 3 channels apart: 25% overlap
        # - 4 channels apart: ~12% overlap
        # - 5+ channels apart: no overlap

        overlap_factors = {1: 0.75, 2: 0.50, 3: 0.25, 4: 0.12}

        for channel, score in scores.items():
            if score.band != BAND_2_4_GHZ:
                continue

            penalty = 0.0
            for other_channel, other_score in scores.items():
                if other_channel == channel or other_score.band != BAND_2_4_GHZ:
                    continue

                distance = abs(channel - other_channel)
                if distance in overlap_factors:
                    # Penalty based on APs on overlapping channel
                    overlap = overlap_factors[distance]
                    penalty += other_score.ap_count * overlap * 0.5

            score.overlap_penalty = penalty

    def _build_channel_stats(self, scores: dict[int, ChannelScore]) -> list[ChannelStats]:
        """Build ChannelStats from scores."""
        stats_list = []

        for channel, score in sorted(scores.items()):
            rssi_avg = None
            if score.rssi_count > 0:
                rssi_avg = score.rssi_sum / score.rssi_count

            # Calculate utilization score
            utilization = self._calculate_utilization(score)

            stats = ChannelStats(
                channel=channel,
                band=score.band,
                frequency_mhz=CHANNEL_FREQUENCIES.get(channel),
                ap_count=score.ap_count,
                client_count=score.client_count,
                rssi_avg=rssi_avg,
                utilization_score=utilization,
            )
            stats_list.append(stats)

        return stats_list

    def _calculate_utilization(self, score: ChannelScore) -> float:
        """Calculate channel utilization score (0.0-1.0, lower is better)."""
        # Base score from AP and client counts
        ap_score = score.ap_count * self.ap_weight
        client_score = score.client_count * self.client_weight

        # RSSI adjustment: stronger signals = more interference
        rssi_adjustment = 0.0
        if score.rssi_count > 0:
            avg_rssi = score.rssi_sum / score.rssi_count
            # Normalize: -30 dBm (very strong) -> 1.0, -100 dBm (weak) -> 0.0
            rssi_normalized = (avg_rssi + 100) / 70
            rssi_adjustment = max(0, rssi_normalized) * self.rssi_factor * score.ap_count

        # Overlap penalty (already scaled)
        overlap_score = score.overlap_penalty

        # Total score
        total = ap_score + client_score + rssi_adjustment + overlap_score

        # Normalize to 0.0-1.0 range (cap at reasonable maximum)
        normalized = min(1.0, total / 10.0)

        return normalized

    def _generate_recommendations(
        self,
        scores: dict[int, ChannelScore],
        access_points: list[WiFiAccessPoint],
        include_dfs: bool,
    ) -> list[ChannelRecommendation]:
        """Generate channel recommendations."""
        recommendations = []

        # Score all non-overlapping channels
        candidate_channels = []

        # 2.4 GHz non-overlapping
        for channel in NON_OVERLAPPING_2_4_GHZ:
            candidate_channels.append((channel, BAND_2_4_GHZ, False))

        # 5 GHz non-DFS
        for channel in NON_OVERLAPPING_5_GHZ:
            is_dfs = channel in DFS_CHANNELS_5_GHZ
            if is_dfs and not include_dfs:
                continue
            candidate_channels.append((channel, BAND_5_GHZ, is_dfs))

        # 5 GHz DFS channels (if requested)
        if include_dfs:
            for channel in DFS_CHANNELS_5_GHZ:
                if channel not in NON_OVERLAPPING_5_GHZ:
                    candidate_channels.append((channel, BAND_5_GHZ, True))

        # Score each candidate
        for channel, band, is_dfs in candidate_channels:
            score = scores.get(channel)

            if score:
                utilization = self._calculate_utilization(score)
                ap_count = score.ap_count
            else:
                utilization = 0.0
                ap_count = 0

            # Build reason string
            if ap_count == 0:
                reason = "No APs detected - clear channel"
            elif ap_count == 1:
                reason = f"1 AP on channel"
            else:
                reason = f"{ap_count} APs on channel"

            if is_dfs:
                reason += " (DFS - radar detection required)"

            recommendations.append(ChannelRecommendation(
                channel=channel,
                band=band,
                score=utilization,
                reason=reason,
                is_dfs=is_dfs,
            ))

        # Sort by score (lower is better), then prefer non-DFS
        recommendations.sort(key=lambda r: (r.score, r.is_dfs, r.channel))

        return recommendations


# Module-level convenience function
def analyze_channels(
    access_points: list[WiFiAccessPoint],
    include_dfs: bool = False,
) -> tuple[list[ChannelStats], list[ChannelRecommendation]]:
    """
    Analyze channel utilization and get recommendations.

    Args:
        access_points: List of discovered access points.
        include_dfs: Whether to include DFS channels.

    Returns:
        Tuple of (channel_stats, recommendations).
    """
    analyzer = ChannelAnalyzer()
    return analyzer.analyze(access_points, include_dfs)
