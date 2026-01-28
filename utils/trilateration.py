"""
Trilateration/Multilateration utilities for estimating device locations
from multiple agent observations using RSSI signal strength.

This module enables location estimation for devices that don't transmit
their own GPS coordinates (WiFi APs, Bluetooth devices, etc.) by using
signal strength measurements from multiple agents at known positions.
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from datetime import datetime, timezone

logger = logging.getLogger('intercept.trilateration')


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class AgentObservation:
    """A single observation of a device by an agent."""
    agent_name: str
    agent_lat: float
    agent_lon: float
    rssi: float  # dBm
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    frequency_mhz: Optional[float] = None  # For frequency-dependent path loss


@dataclass
class LocationEstimate:
    """Estimated location of a device with confidence metrics."""
    latitude: float
    longitude: float
    accuracy_meters: float  # Estimated accuracy radius
    confidence: float  # 0.0 to 1.0
    num_observations: int
    observations: List[AgentObservation] = field(default_factory=list)
    method: str = "multilateration"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dictionary."""
        return {
            'latitude': self.latitude,
            'longitude': self.longitude,
            'accuracy_meters': self.accuracy_meters,
            'confidence': self.confidence,
            'num_observations': self.num_observations,
            'method': self.method,
            'timestamp': self.timestamp.isoformat(),
            'agents': [obs.agent_name for obs in self.observations]
        }


# =============================================================================
# Path Loss Models
# =============================================================================

class PathLossModel:
    """
    Convert RSSI to estimated distance using path loss models.

    The free-space path loss (FSPL) model is:
        FSPL(dB) = 20*log10(d) + 20*log10(f) - 147.55

    Rearranged for distance:
        d = 10^((RSSI_ref - RSSI) / (10 * n))

    Where:
        - n is the path loss exponent (2 for free space, 2.5-4 for indoor)
        - RSSI_ref is the RSSI at 1 meter reference distance
    """

    # Default parameters for different environments
    ENVIRONMENTS = {
        'free_space': {'n': 2.0, 'rssi_ref': -40},
        'outdoor': {'n': 2.5, 'rssi_ref': -45},
        'indoor': {'n': 3.0, 'rssi_ref': -50},
        'indoor_obstructed': {'n': 4.0, 'rssi_ref': -55},
    }

    # Frequency-specific reference RSSI adjustments (WiFi vs Bluetooth)
    FREQUENCY_ADJUSTMENTS = {
        2400: 0,      # 2.4 GHz WiFi/Bluetooth - baseline
        5000: -3,     # 5 GHz WiFi - weaker propagation
        900: +5,      # 900 MHz ISM - better propagation
        433: +8,      # 433 MHz sensors - even better
    }

    def __init__(
        self,
        environment: str = 'outdoor',
        path_loss_exponent: Optional[float] = None,
        reference_rssi: Optional[float] = None
    ):
        """
        Initialize path loss model.

        Args:
            environment: One of 'free_space', 'outdoor', 'indoor', 'indoor_obstructed'
            path_loss_exponent: Override the environment's default n value
            reference_rssi: Override the environment's default RSSI at 1m
        """
        env_params = self.ENVIRONMENTS.get(environment, self.ENVIRONMENTS['outdoor'])
        self.n = path_loss_exponent if path_loss_exponent is not None else env_params['n']
        self.rssi_ref = reference_rssi if reference_rssi is not None else env_params['rssi_ref']

    def rssi_to_distance(
        self,
        rssi: float,
        frequency_mhz: Optional[float] = None
    ) -> float:
        """
        Convert RSSI to estimated distance in meters.

        Args:
            rssi: Measured RSSI in dBm
            frequency_mhz: Signal frequency for adjustment (optional)

        Returns:
            Estimated distance in meters
        """
        # Apply frequency adjustment if known
        adjusted_ref = self.rssi_ref
        if frequency_mhz:
            for freq, adj in self.FREQUENCY_ADJUSTMENTS.items():
                if abs(frequency_mhz - freq) < 500:
                    adjusted_ref += adj
                    break

        # Calculate distance using log-distance path loss model
        # d = 10^((RSSI_ref - RSSI) / (10 * n))
        try:
            exponent = (adjusted_ref - rssi) / (10.0 * self.n)
            distance = math.pow(10, exponent)

            # Sanity bounds
            distance = max(0.5, min(distance, 10000))
            return distance
        except (ValueError, OverflowError):
            return 100.0  # Default fallback

    def distance_to_rssi(
        self,
        distance: float,
        frequency_mhz: Optional[float] = None
    ) -> float:
        """
        Estimate RSSI at a given distance (inverse of rssi_to_distance).
        Useful for testing and validation.
        """
        if distance <= 0:
            distance = 0.5

        adjusted_ref = self.rssi_ref
        if frequency_mhz:
            for freq, adj in self.FREQUENCY_ADJUSTMENTS.items():
                if abs(frequency_mhz - freq) < 500:
                    adjusted_ref += adj
                    break

        # RSSI = RSSI_ref - 10 * n * log10(d)
        rssi = adjusted_ref - (10.0 * self.n * math.log10(distance))
        return rssi


# =============================================================================
# Geographic Utilities
# =============================================================================

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great-circle distance between two points in meters.

    Uses the Haversine formula for accuracy on Earth's surface.
    """
    R = 6371000  # Earth's radius in meters

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def meters_to_degrees(meters: float, latitude: float) -> Tuple[float, float]:
    """
    Convert meters to approximate degrees at a given latitude.

    Returns (lat_degrees, lon_degrees) for the given distance.
    """
    # Latitude: roughly constant at ~111km per degree
    lat_deg = meters / 111000.0

    # Longitude: varies with latitude
    lon_deg = meters / (111000.0 * math.cos(math.radians(latitude)))

    return lat_deg, lon_deg


def offset_position(lat: float, lon: float, north_m: float, east_m: float) -> Tuple[float, float]:
    """
    Offset a GPS position by meters north and east.

    Returns (new_lat, new_lon).
    """
    lat_offset = north_m / 111000.0
    lon_offset = east_m / (111000.0 * math.cos(math.radians(lat)))

    return lat + lat_offset, lon + lon_offset


# =============================================================================
# Trilateration Algorithm
# =============================================================================

class Trilateration:
    """
    Estimate device location using multilateration from multiple RSSI observations.

    Multilateration works by:
    1. Converting RSSI to estimated distance from each observer
    2. Finding the point that minimizes the sum of squared distance errors
    3. Using iterative refinement for better accuracy
    """

    def __init__(
        self,
        path_loss_model: Optional[PathLossModel] = None,
        min_observations: int = 2,
        max_iterations: int = 100,
        convergence_threshold: float = 0.1  # meters
    ):
        """
        Initialize trilateration engine.

        Args:
            path_loss_model: Model for RSSI to distance conversion
            min_observations: Minimum number of observations required
            max_iterations: Maximum iterations for refinement
            convergence_threshold: Stop when movement is less than this (meters)
        """
        self.path_loss = path_loss_model or PathLossModel()
        self.min_observations = min_observations
        self.max_iterations = max_iterations
        self.convergence_threshold = convergence_threshold

    def estimate_location(
        self,
        observations: List[AgentObservation]
    ) -> Optional[LocationEstimate]:
        """
        Estimate device location from multiple agent observations.

        Args:
            observations: List of observations from different agents

        Returns:
            LocationEstimate if successful, None if insufficient data
        """
        if len(observations) < self.min_observations:
            logger.debug(f"Insufficient observations: {len(observations)} < {self.min_observations}")
            return None

        # Filter out observations with invalid coordinates
        valid_obs = [
            obs for obs in observations
            if obs.agent_lat is not None and obs.agent_lon is not None
            and -90 <= obs.agent_lat <= 90 and -180 <= obs.agent_lon <= 180
        ]

        if len(valid_obs) < self.min_observations:
            return None

        # Convert RSSI to estimated distances
        distances = []
        for obs in valid_obs:
            dist = self.path_loss.rssi_to_distance(obs.rssi, obs.frequency_mhz)
            distances.append(dist)

        # Use weighted centroid as initial estimate
        # Weight by inverse distance (closer observations weighted more)
        weights = [1.0 / max(d, 1.0) for d in distances]
        total_weight = sum(weights)

        initial_lat = sum(obs.agent_lat * w for obs, w in zip(valid_obs, weights)) / total_weight
        initial_lon = sum(obs.agent_lon * w for obs, w in zip(valid_obs, weights)) / total_weight

        # Iterative refinement using gradient descent
        current_lat, current_lon = initial_lat, initial_lon

        for iteration in range(self.max_iterations):
            # Calculate gradient of error function
            grad_lat = 0.0
            grad_lon = 0.0
            total_error = 0.0

            for obs, expected_dist in zip(valid_obs, distances):
                actual_dist = haversine_distance(
                    current_lat, current_lon,
                    obs.agent_lat, obs.agent_lon
                )

                error = actual_dist - expected_dist
                total_error += error ** 2

                if actual_dist > 0.1:  # Avoid division by zero
                    # Gradient components
                    lat_diff = current_lat - obs.agent_lat
                    lon_diff = current_lon - obs.agent_lon

                    # Scale factor for lat/lon to meters
                    lat_scale = 111000.0
                    lon_scale = 111000.0 * math.cos(math.radians(current_lat))

                    grad_lat += error * (lat_diff * lat_scale) / actual_dist
                    grad_lon += error * (lon_diff * lon_scale) / actual_dist

            # Adaptive learning rate based on error magnitude
            rmse = math.sqrt(total_error / len(valid_obs))
            learning_rate = min(0.5, rmse / 1000.0) / (iteration + 1)

            # Update position
            lat_delta = -learning_rate * grad_lat / 111000.0
            lon_delta = -learning_rate * grad_lon / (111000.0 * math.cos(math.radians(current_lat)))

            new_lat = current_lat + lat_delta
            new_lon = current_lon + lon_delta

            # Check convergence
            movement = haversine_distance(current_lat, current_lon, new_lat, new_lon)

            current_lat = new_lat
            current_lon = new_lon

            if movement < self.convergence_threshold:
                break

        # Calculate accuracy estimate (average distance error)
        total_error = 0.0
        for obs, expected_dist in zip(valid_obs, distances):
            actual_dist = haversine_distance(
                current_lat, current_lon,
                obs.agent_lat, obs.agent_lon
            )
            total_error += abs(actual_dist - expected_dist)

        avg_error = total_error / len(valid_obs)

        # Calculate confidence based on:
        # - Number of observations (more is better)
        # - Agreement between observations (lower error is better)
        # - RSSI strength (stronger signals are more reliable)

        obs_factor = min(1.0, len(valid_obs) / 4.0)  # Max confidence at 4+ observations
        error_factor = max(0.0, 1.0 - avg_error / 500.0)  # Decreases as error increases
        rssi_factor = min(1.0, max(0.0, (max(obs.rssi for obs in valid_obs) + 90) / 50.0))

        confidence = (obs_factor * 0.3 + error_factor * 0.5 + rssi_factor * 0.2)

        return LocationEstimate(
            latitude=current_lat,
            longitude=current_lon,
            accuracy_meters=avg_error * 1.5,  # Safety factor
            confidence=confidence,
            num_observations=len(valid_obs),
            observations=valid_obs,
            method="multilateration"
        )


# =============================================================================
# Device Location Tracker
# =============================================================================

class DeviceLocationTracker:
    """
    Track device locations over time using observations from multiple agents.

    This class aggregates observations for each device (by identifier like MAC address)
    and periodically computes location estimates.
    """

    def __init__(
        self,
        trilateration: Optional[Trilateration] = None,
        observation_window_seconds: float = 60.0,
        min_observations: int = 2
    ):
        """
        Initialize device tracker.

        Args:
            trilateration: Trilateration engine to use
            observation_window_seconds: How long to keep observations
            min_observations: Minimum observations needed for location
        """
        self.trilateration = trilateration or Trilateration()
        self.observation_window = observation_window_seconds
        self.min_observations = min_observations

        # device_id -> list of AgentObservation
        self.observations: dict[str, List[AgentObservation]] = {}

        # device_id -> latest LocationEstimate
        self.locations: dict[str, LocationEstimate] = {}

    def add_observation(
        self,
        device_id: str,
        agent_name: str,
        agent_lat: float,
        agent_lon: float,
        rssi: float,
        frequency_mhz: Optional[float] = None,
        timestamp: Optional[datetime] = None
    ) -> Optional[LocationEstimate]:
        """
        Add an observation and potentially update location estimate.

        Args:
            device_id: Unique identifier for the device (MAC, BSSID, etc.)
            agent_name: Name of the observing agent
            agent_lat: Agent's GPS latitude
            agent_lon: Agent's GPS longitude
            rssi: Observed signal strength in dBm
            frequency_mhz: Signal frequency (optional)
            timestamp: Observation time (defaults to now)

        Returns:
            Updated LocationEstimate if enough data, None otherwise
        """
        obs = AgentObservation(
            agent_name=agent_name,
            agent_lat=agent_lat,
            agent_lon=agent_lon,
            rssi=rssi,
            frequency_mhz=frequency_mhz,
            timestamp=timestamp or datetime.now(timezone.utc)
        )

        if device_id not in self.observations:
            self.observations[device_id] = []

        self.observations[device_id].append(obs)

        # Prune old observations
        self._prune_observations(device_id)

        # Try to compute/update location
        return self._update_location(device_id)

    def _prune_observations(self, device_id: str) -> None:
        """Remove observations older than the window."""
        now = datetime.now(timezone.utc)
        cutoff = now.timestamp() - self.observation_window

        self.observations[device_id] = [
            obs for obs in self.observations[device_id]
            if obs.timestamp.timestamp() > cutoff
        ]

    def _update_location(self, device_id: str) -> Optional[LocationEstimate]:
        """Compute location estimate from current observations."""
        obs_list = self.observations.get(device_id, [])

        # Get unique agents (use most recent observation per agent)
        agent_obs: dict[str, AgentObservation] = {}
        for obs in obs_list:
            if obs.agent_name not in agent_obs or obs.timestamp > agent_obs[obs.agent_name].timestamp:
                agent_obs[obs.agent_name] = obs

        unique_observations = list(agent_obs.values())

        if len(unique_observations) < self.min_observations:
            return None

        estimate = self.trilateration.estimate_location(unique_observations)

        if estimate:
            self.locations[device_id] = estimate

        return estimate

    def get_location(self, device_id: str) -> Optional[LocationEstimate]:
        """Get the latest location estimate for a device."""
        return self.locations.get(device_id)

    def get_all_locations(self) -> dict[str, LocationEstimate]:
        """Get all current location estimates."""
        return dict(self.locations)

    def get_devices_near(
        self,
        lat: float,
        lon: float,
        radius_meters: float
    ) -> List[Tuple[str, LocationEstimate]]:
        """Find all tracked devices within radius of a point."""
        results = []
        for device_id, estimate in self.locations.items():
            dist = haversine_distance(lat, lon, estimate.latitude, estimate.longitude)
            if dist <= radius_meters:
                results.append((device_id, estimate))
        return results

    def clear(self) -> None:
        """Clear all observations and locations."""
        self.observations.clear()
        self.locations.clear()


# =============================================================================
# Convenience Functions
# =============================================================================

def estimate_location_from_observations(
    observations: List[dict],
    environment: str = 'outdoor'
) -> Optional[dict]:
    """
    Convenience function to estimate location from a list of observation dicts.

    Args:
        observations: List of dicts with keys:
            - agent_lat: float
            - agent_lon: float
            - rssi: float (dBm)
            - agent_name: str (optional)
            - frequency_mhz: float (optional)
        environment: Path loss environment ('outdoor', 'indoor', etc.)

    Returns:
        Location dict or None if insufficient data

    Example:
        observations = [
            {'agent_lat': 40.7128, 'agent_lon': -74.0060, 'rssi': -55, 'agent_name': 'node-1'},
            {'agent_lat': 40.7135, 'agent_lon': -74.0055, 'rssi': -70, 'agent_name': 'node-2'},
            {'agent_lat': 40.7120, 'agent_lon': -74.0050, 'rssi': -62, 'agent_name': 'node-3'},
        ]
        result = estimate_location_from_observations(observations)
        # result: {'latitude': 40.7130, 'longitude': -74.0056, 'accuracy_meters': 25, ...}
    """
    obs_list = []
    for obs in observations:
        obs_list.append(AgentObservation(
            agent_name=obs.get('agent_name', 'unknown'),
            agent_lat=obs['agent_lat'],
            agent_lon=obs['agent_lon'],
            rssi=obs['rssi'],
            frequency_mhz=obs.get('frequency_mhz')
        ))

    trilat = Trilateration(
        path_loss_model=PathLossModel(environment=environment)
    )

    estimate = trilat.estimate_location(obs_list)
    return estimate.to_dict() if estimate else None
