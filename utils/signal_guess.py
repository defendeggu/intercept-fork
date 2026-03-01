"""
Signal Guessing Engine

Heuristic-based signal identification that provides plain-English guesses
for detected signals based on frequency, modulation, bandwidth, and behavior.

All outputs use hedged language - never claims certainty, uses
"likely", "consistent with", "could be" phrasing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# =============================================================================
# Confidence Levels
# =============================================================================

class Confidence(Enum):
    """Signal identification confidence level."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# =============================================================================
# Signal Type Definitions
# =============================================================================

@dataclass
class SignalTypeDefinition:
    """Definition of a known signal type with matching criteria."""
    label: str
    tags: list[str]
    description: str
    # Frequency ranges in Hz: list of (min_hz, max_hz) tuples
    frequency_ranges: list[tuple[int, int]]
    # Optional modulation hints (if provided, boosts confidence)
    modulation_hints: list[str] = field(default_factory=list)
    # Optional bandwidth range (min_hz, max_hz) - if provided, used for scoring
    bandwidth_range: Optional[tuple[int, int]] = None
    # Base score for frequency match
    base_score: int = 10
    # Is this a burst/telemetry type signal?
    is_burst_type: bool = False
    # Region applicability
    regions: list[str] = field(default_factory=lambda: ["UK/EU", "US", "GLOBAL"])


# =============================================================================
# Frequency Range Tables (UK/EU focus, with US variants)
# =============================================================================

# All frequencies in Hz
SIGNAL_TYPES: list[SignalTypeDefinition] = [
    # FM Broadcast Radio
    SignalTypeDefinition(
        label="FM Broadcast Radio",
        tags=["broadcast", "commercial", "wideband"],
        description="Commercial FM radio station transmission",
        frequency_ranges=[
            (87_500_000, 108_000_000),  # 87.5 - 108 MHz
        ],
        modulation_hints=["WFM", "FM", "WBFM"],
        bandwidth_range=(150_000, 250_000),  # ~200 kHz typical
        base_score=15,
        regions=["UK/EU", "US", "GLOBAL"],
    ),

    # Civil Aviation / Airband
    SignalTypeDefinition(
        label="Airband (Civil Aviation Voice)",
        tags=["aviation", "voice", "aeronautical"],
        description="Civil aviation voice communications",
        frequency_ranges=[
            (118_000_000, 137_000_000),  # 118 - 137 MHz (international)
        ],
        modulation_hints=["AM", "A3E"],
        bandwidth_range=(6_000, 10_000),  # ~8 kHz AM voice
        base_score=15,
        regions=["UK/EU", "US", "GLOBAL"],
    ),

    # ISM 433 MHz (EU)
    SignalTypeDefinition(
        label="ISM Device (433 MHz)",
        tags=["ism", "short-range", "telemetry", "consumer"],
        description="Industrial, Scientific, Medical band device",
        frequency_ranges=[
            (433_050_000, 434_790_000),  # 433.05 - 434.79 MHz (EU ISM)
        ],
        modulation_hints=["OOK", "ASK", "FSK", "NFM", "FM"],
        bandwidth_range=(10_000, 50_000),
        base_score=12,
        is_burst_type=True,
        regions=["UK/EU"],
    ),

    # ISM 315 MHz (US)
    SignalTypeDefinition(
        label="ISM Device (315 MHz)",
        tags=["ism", "short-range", "telemetry", "consumer"],
        description="Industrial, Scientific, Medical band device (US)",
        frequency_ranges=[
            (315_000_000, 316_000_000),  # 315 MHz US ISM
        ],
        modulation_hints=["OOK", "ASK", "FSK"],
        bandwidth_range=(10_000, 50_000),
        base_score=12,
        is_burst_type=True,
        regions=["US"],
    ),

    # ISM 868 MHz (EU)
    SignalTypeDefinition(
        label="ISM Device (868 MHz)",
        tags=["ism", "short-range", "telemetry", "iot"],
        description="868 MHz ISM band device (LoRa, sensors, IoT)",
        frequency_ranges=[
            (868_000_000, 868_600_000),  # 868 MHz EU ISM
            (869_400_000, 869_650_000),  # 869 MHz EU ISM (higher power)
        ],
        modulation_hints=["FSK", "GFSK", "LoRa", "OOK", "NFM"],
        bandwidth_range=(10_000, 150_000),
        base_score=12,
        is_burst_type=True,
        regions=["UK/EU"],
    ),

    # ISM 915 MHz (US)
    SignalTypeDefinition(
        label="ISM Device (915 MHz)",
        tags=["ism", "short-range", "telemetry", "iot"],
        description="915 MHz ISM band device (US/Americas)",
        frequency_ranges=[
            (902_000_000, 928_000_000),  # 902-928 MHz US ISM
        ],
        modulation_hints=["FSK", "GFSK", "LoRa", "OOK", "NFM", "FHSS"],
        bandwidth_range=(10_000, 500_000),
        base_score=12,
        is_burst_type=True,
        regions=["US"],
    ),

    # ISM 2.4 GHz (Global)
    SignalTypeDefinition(
        label="ISM Device (2.4 GHz)",
        tags=["ism", "wifi", "bluetooth", "wireless"],
        description="2.4 GHz ISM band (WiFi, Bluetooth, wireless devices)",
        frequency_ranges=[
            (2_400_000_000, 2_483_500_000),  # 2.4 GHz ISM
        ],
        modulation_hints=["OFDM", "DSSS", "FHSS", "GFSK", "WiFi", "BT"],
        bandwidth_range=(1_000_000, 40_000_000),  # 1-40 MHz depending on protocol
        base_score=10,
        regions=["UK/EU", "US", "GLOBAL"],
    ),

    # ISM 5.8 GHz (Global)
    SignalTypeDefinition(
        label="ISM Device (5.8 GHz)",
        tags=["ism", "wifi", "wireless", "video"],
        description="5.8 GHz ISM band (WiFi, video links, wireless devices)",
        frequency_ranges=[
            (5_725_000_000, 5_875_000_000),  # 5.8 GHz ISM
        ],
        modulation_hints=["OFDM", "WiFi"],
        bandwidth_range=(10_000_000, 80_000_000),
        base_score=10,
        regions=["UK/EU", "US", "GLOBAL"],
    ),

    # TPMS / Tire Pressure Monitoring
    SignalTypeDefinition(
        label="TPMS / Vehicle Telemetry",
        tags=["telemetry", "automotive", "burst", "tpms"],
        description="Tire pressure monitoring or similar vehicle telemetry",
        frequency_ranges=[
            (314_900_000, 315_100_000),  # 315 MHz (US TPMS)
            (433_800_000, 434_000_000),  # 433.92 MHz (EU TPMS)
            (433_900_000, 433_940_000),  # Narrow 433.92 MHz
        ],
        modulation_hints=["OOK", "ASK", "FSK", "NFM"],
        bandwidth_range=(10_000, 40_000),
        base_score=10,
        is_burst_type=True,
        regions=["UK/EU", "US"],
    ),

    # Cellular / LTE (broad category)
    SignalTypeDefinition(
        label="Cellular / Mobile Network",
        tags=["cellular", "lte", "mobile", "wideband"],
        description="Mobile network transmission (2G/3G/4G/5G)",
        frequency_ranges=[
            # UK/EU common bands
            (791_000_000, 862_000_000),    # Band 20 (800 MHz)
            (880_000_000, 960_000_000),    # Band 8 (900 MHz GSM/UMTS)
            (1_710_000_000, 1_880_000_000), # Band 3 (1800 MHz)
            (1_920_000_000, 2_170_000_000), # Band 1 (2100 MHz UMTS)
            (2_500_000_000, 2_690_000_000), # Band 7 (2600 MHz)
            # US common bands
            (698_000_000, 756_000_000),    # Band 12/17 (700 MHz)
            (824_000_000, 894_000_000),    # Band 5 (850 MHz)
            (1_850_000_000, 1_995_000_000), # Band 2/25 (1900 MHz PCS)
        ],
        modulation_hints=["OFDM", "QAM", "LTE", "4G", "5G", "GSM", "UMTS"],
        bandwidth_range=(200_000, 20_000_000),  # 200 kHz (GSM) to 20 MHz (LTE)
        base_score=8,  # Lower base due to broad category
        regions=["UK/EU", "US", "GLOBAL"],
    ),

    # PMR446 (EU license-free)
    SignalTypeDefinition(
        label="PMR446 Radio",
        tags=["pmr", "voice", "handheld", "license-free"],
        description="License-free handheld radio communications",
        frequency_ranges=[
            (446_000_000, 446_200_000),  # PMR446 EU
        ],
        modulation_hints=["NFM", "FM", "DPMR", "dPMR"],
        bandwidth_range=(6_250, 12_500),
        base_score=14,
        regions=["UK/EU"],
    ),

    # Marine VHF
    SignalTypeDefinition(
        label="Marine VHF Radio",
        tags=["marine", "maritime", "voice", "nautical"],
        description="Marine VHF voice communications",
        frequency_ranges=[
            (156_000_000, 162_025_000),  # Marine VHF band
        ],
        modulation_hints=["NFM", "FM"],
        bandwidth_range=(12_500, 25_000),
        base_score=14,
        regions=["UK/EU", "US", "GLOBAL"],
    ),

    # Amateur Radio 2m
    SignalTypeDefinition(
        label="Amateur Radio (2m)",
        tags=["amateur", "ham", "voice", "vhf"],
        description="Amateur radio 2-meter band",
        frequency_ranges=[
            (144_000_000, 148_000_000),  # 2m band (Region 1 & 2 overlap)
        ],
        modulation_hints=["NFM", "FM", "SSB", "USB", "LSB", "CW"],
        bandwidth_range=(2_400, 15_000),
        base_score=12,
        regions=["UK/EU", "US", "GLOBAL"],
    ),

    # Amateur Radio 70cm
    SignalTypeDefinition(
        label="Amateur Radio (70cm)",
        tags=["amateur", "ham", "voice", "uhf"],
        description="Amateur radio 70-centimeter band",
        frequency_ranges=[
            (430_000_000, 440_000_000),  # 70cm band
        ],
        modulation_hints=["NFM", "FM", "SSB", "USB", "LSB", "CW", "D-STAR", "DMR"],
        bandwidth_range=(2_400, 15_000),
        base_score=12,
        regions=["UK/EU", "US", "GLOBAL"],
    ),

    # DECT Cordless Phones
    SignalTypeDefinition(
        label="DECT Cordless Phone",
        tags=["dect", "cordless", "telephony", "consumer"],
        description="Digital Enhanced Cordless Telecommunications",
        frequency_ranges=[
            (1_880_000_000, 1_900_000_000),  # DECT EU
            (1_920_000_000, 1_930_000_000),  # DECT US
        ],
        modulation_hints=["GFSK", "DECT"],
        bandwidth_range=(1_728_000, 1_728_000),  # Fixed 1.728 MHz
        base_score=12,
        regions=["UK/EU", "US"],
    ),

    # DAB Digital Radio
    SignalTypeDefinition(
        label="DAB Digital Radio",
        tags=["broadcast", "digital", "dab", "wideband"],
        description="Digital Audio Broadcasting radio",
        frequency_ranges=[
            (174_000_000, 240_000_000),  # DAB Band III
        ],
        modulation_hints=["OFDM", "DAB", "DAB+"],
        bandwidth_range=(1_500_000, 1_600_000),  # ~1.5 MHz per multiplex
        base_score=14,
        regions=["UK/EU"],
    ),

    # Pager (POCSAG/FLEX)
    SignalTypeDefinition(
        label="Pager Network",
        tags=["pager", "pocsag", "flex", "messaging"],
        description="Paging network transmission (POCSAG/FLEX)",
        frequency_ranges=[
            (153_000_000, 154_000_000),  # UK pager frequencies
            (466_000_000, 467_000_000),  # Additional pager band
            (929_000_000, 932_000_000),  # US pager band
        ],
        modulation_hints=["FSK", "POCSAG", "FLEX"],
        bandwidth_range=(12_500, 25_000),
        base_score=13,
        regions=["UK/EU", "US"],
    ),

    # Weather Satellite (NOAA APT)
    SignalTypeDefinition(
        label="Weather Satellite (NOAA)",
        tags=["satellite", "weather", "apt", "noaa"],
        description="NOAA weather satellite APT transmission",
        frequency_ranges=[
            (137_000_000, 138_000_000),  # NOAA APT
        ],
        modulation_hints=["APT", "FM", "NFM"],
        bandwidth_range=(34_000, 40_000),
        base_score=14,
        regions=["GLOBAL"],
    ),

    # ADS-B
    SignalTypeDefinition(
        label="ADS-B Aircraft Tracking",
        tags=["aviation", "adsb", "surveillance", "tracking"],
        description="Automatic Dependent Surveillance-Broadcast",
        frequency_ranges=[
            (1_090_000_000, 1_090_000_000),  # 1090 MHz exactly
        ],
        modulation_hints=["PPM", "ADSB"],
        bandwidth_range=(1_000_000, 2_000_000),
        base_score=15,
        is_burst_type=True,
        regions=["GLOBAL"],
    ),

    # Key Fob / Remote
    SignalTypeDefinition(
        label="Remote Control / Key Fob",
        tags=["remote", "keyfob", "automotive", "burst", "ism"],
        description="Wireless remote control or vehicle key fob",
        frequency_ranges=[
            (314_900_000, 315_100_000),  # 315 MHz (US)
            (433_050_000, 434_790_000),  # 433 MHz (EU)
            (867_000_000, 869_000_000),  # 868 MHz (EU)
        ],
        modulation_hints=["OOK", "ASK", "FSK", "rolling"],
        bandwidth_range=(10_000, 50_000),
        base_score=10,
        is_burst_type=True,
        regions=["UK/EU", "US"],
    ),
]


# =============================================================================
# Signal Guess Result
# =============================================================================

@dataclass
class SignalAlternative:
    """An alternative signal type guess."""
    label: str
    confidence: Confidence
    score: int


@dataclass
class SignalGuessResult:
    """Complete signal guess result with hedged language."""
    primary_label: str
    confidence: Confidence
    alternatives: list[SignalAlternative]
    explanation: str
    tags: list[str]
    # Internal scoring data (useful for debugging/testing)
    _scores: dict[str, int] = field(default_factory=dict, repr=False)


# =============================================================================
# Signal Guessing Engine
# =============================================================================

class SignalGuessingEngine:
    """
    Heuristic-based signal identification engine.

    Provides plain-English guesses for detected signals based on frequency,
    modulation, bandwidth, and behavioral characteristics.

    All outputs use hedged language - never claims certainty.
    """

    def __init__(self, region: str = "UK/EU"):
        """
        Initialize the guessing engine.

        Args:
            region: Default region for frequency allocations.
                    Options: "UK/EU", "US", "GLOBAL"
        """
        self.region = region
        self._signal_types = SIGNAL_TYPES

    def guess_signal_type(
        self,
        frequency_hz: int,
        modulation: Optional[str] = None,
        bandwidth_hz: Optional[int] = None,
        duration_ms: Optional[int] = None,
        repetition_count: Optional[int] = None,
        rssi_dbm: Optional[float] = None,
        region: Optional[str] = None,
    ) -> SignalGuessResult:
        """
        Guess the signal type based on detection parameters.

        Args:
            frequency_hz: Center frequency in Hz (required)
            modulation: Modulation type string (e.g., "FM", "AM", "NFM")
            bandwidth_hz: Estimated signal bandwidth in Hz
            duration_ms: How long the signal was observed in milliseconds
            repetition_count: How many times seen recently
            rssi_dbm: Signal strength in dBm
            region: Override default region

        Returns:
            SignalGuessResult with primary guess, alternatives, and explanation
        """
        effective_region = region or self.region

        # Score all signal types
        scores: dict[str, int] = {}
        matched_types: dict[str, SignalTypeDefinition] = {}

        for signal_type in self._signal_types:
            score = self._score_signal_type(
                signal_type,
                frequency_hz,
                modulation,
                bandwidth_hz,
                duration_ms,
                repetition_count,
                effective_region,
            )
            if score > 0:
                scores[signal_type.label] = score
                matched_types[signal_type.label] = signal_type

        # If no matches, return unknown
        if not scores:
            return SignalGuessResult(
                primary_label="Unknown Signal",
                confidence=Confidence.LOW,
                alternatives=[],
                explanation=self._build_unknown_explanation(frequency_hz, modulation),
                tags=["unknown"],
                _scores={},
            )

        # Sort by score descending
        sorted_labels = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

        # Primary guess
        primary_label = sorted_labels[0]
        primary_score = scores[primary_label]
        primary_type = matched_types[primary_label]

        # Calculate confidence based on score and margin
        confidence = self._calculate_confidence(
            primary_score,
            scores,
            sorted_labels,
            modulation,
            bandwidth_hz,
        )

        # Build alternatives (up to 3, excluding primary)
        alternatives = []
        for label in sorted_labels[1:4]:  # Next 3 candidates
            alt_score = scores[label]
            # Alternative confidence is always at most one level below primary
            # unless scores are very close
            alt_confidence = self._calculate_alternative_confidence(
                alt_score, primary_score, confidence
            )
            alternatives.append(SignalAlternative(
                label=label,
                confidence=alt_confidence,
                score=alt_score,
            ))

        # Build explanation
        explanation = self._build_explanation(
            primary_type,
            confidence,
            frequency_hz,
            modulation,
            bandwidth_hz,
            duration_ms,
            repetition_count,
        )

        return SignalGuessResult(
            primary_label=primary_label,
            confidence=confidence,
            alternatives=alternatives,
            explanation=explanation,
            tags=primary_type.tags.copy(),
            _scores=scores,
        )

    def _score_signal_type(
        self,
        signal_type: SignalTypeDefinition,
        frequency_hz: int,
        modulation: Optional[str],
        bandwidth_hz: Optional[int],
        duration_ms: Optional[int],
        repetition_count: Optional[int],
        region: str,
    ) -> int:
        """Calculate score for a signal type match."""
        score = 0

        # Check region applicability
        if region not in signal_type.regions and "GLOBAL" not in signal_type.regions:
            return 0

        # Check frequency match (required)
        freq_match = False
        for freq_min, freq_max in signal_type.frequency_ranges:
            if freq_min <= frequency_hz <= freq_max:
                freq_match = True
                break

        if not freq_match:
            return 0

        # Base score for frequency match
        score = signal_type.base_score

        # Modulation bonus
        if modulation:
            mod_upper = modulation.upper()
            for hint in signal_type.modulation_hints:
                if hint.upper() in mod_upper or mod_upper in hint.upper():
                    score += 5
                    break

        # Bandwidth bonus/penalty
        if bandwidth_hz and signal_type.bandwidth_range:
            bw_min, bw_max = signal_type.bandwidth_range
            if bw_min <= bandwidth_hz <= bw_max:
                score += 4  # Good match
            elif bandwidth_hz < bw_min * 0.5 or bandwidth_hz > bw_max * 2:
                score -= 3  # Poor match
            # Otherwise neutral

        # Burst behavior bonus for burst-type signals
        if signal_type.is_burst_type:
            if duration_ms is not None and duration_ms < 1000:  # Short burst < 1 second
                score += 3
            if repetition_count is not None and repetition_count >= 2:
                score += 2  # Multiple bursts suggest telemetry/periodic

        return max(0, score)

    def _calculate_confidence(
        self,
        primary_score: int,
        all_scores: dict[str, int],
        sorted_labels: list[str],
        modulation: Optional[str],
        bandwidth_hz: Optional[int],
    ) -> Confidence:
        """Calculate confidence level based on scores and data quality."""

        # High confidence requires:
        # - High absolute score (>= 18)
        # - Good margin over second place (>= 5 points)
        # - Some supporting data (modulation or bandwidth)

        if len(sorted_labels) == 1:
            # Only one candidate
            if primary_score >= 18 and (modulation or bandwidth_hz):
                return Confidence.HIGH
            elif primary_score >= 14:
                return Confidence.MEDIUM
            return Confidence.LOW

        second_score = all_scores[sorted_labels[1]]
        margin = primary_score - second_score

        if primary_score >= 18 and margin >= 5:
            return Confidence.HIGH
        elif primary_score >= 14 and margin >= 3:
            return Confidence.MEDIUM
        elif primary_score >= 12 and margin >= 2:
            return Confidence.MEDIUM
        return Confidence.LOW

    def _calculate_alternative_confidence(
        self,
        alt_score: int,
        primary_score: int,
        primary_confidence: Confidence,
    ) -> Confidence:
        """Calculate confidence for an alternative guess."""
        score_ratio = alt_score / primary_score if primary_score > 0 else 0

        if score_ratio >= 0.9:
            # Very close to primary - same confidence or one below
            if primary_confidence == Confidence.HIGH:
                return Confidence.MEDIUM
            return primary_confidence
        elif score_ratio >= 0.7:
            # Moderately close
            if primary_confidence == Confidence.HIGH:
                return Confidence.MEDIUM
            return Confidence.LOW
        else:
            return Confidence.LOW

    def _build_explanation(
        self,
        signal_type: SignalTypeDefinition,
        confidence: Confidence,
        frequency_hz: int,
        modulation: Optional[str],
        bandwidth_hz: Optional[int],
        duration_ms: Optional[int],
        repetition_count: Optional[int],
    ) -> str:
        """Build a hedged, client-safe explanation."""
        freq_mhz = frequency_hz / 1_000_000

        # Start with frequency observation
        if confidence == Confidence.HIGH:
            explanation = f"Frequency of {freq_mhz:.3f} MHz is consistent with {signal_type.description.lower()}."
        elif confidence == Confidence.MEDIUM:
            explanation = f"Frequency of {freq_mhz:.3f} MHz could indicate {signal_type.description.lower()}."
        else:
            explanation = f"Frequency of {freq_mhz:.3f} MHz may be associated with {signal_type.description.lower()}."

        # Add supporting evidence
        evidence = []
        if modulation:
            evidence.append(f"{modulation} modulation")
        if bandwidth_hz:
            bw_khz = bandwidth_hz / 1000
            evidence.append(f"~{bw_khz:.0f} kHz bandwidth")
        if duration_ms is not None and duration_ms < 1000:
            evidence.append("short-burst pattern")
        if repetition_count is not None and repetition_count >= 3:
            evidence.append("repeated transmission")

        if evidence:
            evidence_str = ", ".join(evidence)
            if confidence == Confidence.HIGH:
                explanation += f" Observed characteristics ({evidence_str}) support this identification."
            else:
                explanation += f" Observed {evidence_str}."

        return explanation

    def _build_unknown_explanation(
        self,
        frequency_hz: int,
        modulation: Optional[str],
    ) -> str:
        """Build explanation for unknown signal."""
        freq_mhz = frequency_hz / 1_000_000
        if modulation:
            return (
                f"Signal at {freq_mhz:.3f} MHz with {modulation} modulation "
                f"does not match common allocations for this region."
            )
        return (
            f"Signal at {freq_mhz:.3f} MHz does not match common allocations "
            f"for this region. Additional characteristics may help identification."
        )

    def get_frequency_allocations(
        self,
        frequency_hz: int,
        region: Optional[str] = None,
    ) -> list[str]:
        """
        Get all possible allocations for a frequency.

        Useful for displaying what services could operate at a given frequency.
        """
        effective_region = region or self.region
        allocations = []

        for signal_type in self._signal_types:
            if effective_region not in signal_type.regions and "GLOBAL" not in signal_type.regions:
                continue

            for freq_min, freq_max in signal_type.frequency_ranges:
                if freq_min <= frequency_hz <= freq_max:
                    allocations.append(signal_type.label)
                    break

        return allocations


# =============================================================================
# Convenience Functions
# =============================================================================

# Default engine instance
_default_engine: Optional[SignalGuessingEngine] = None


def get_engine(region: str = "UK/EU") -> SignalGuessingEngine:
    """Get or create the default engine instance."""
    global _default_engine
    if _default_engine is None or _default_engine.region != region:
        _default_engine = SignalGuessingEngine(region=region)
    return _default_engine


def guess_signal_type(
    frequency_hz: int,
    modulation: Optional[str] = None,
    bandwidth_hz: Optional[int] = None,
    duration_ms: Optional[int] = None,
    repetition_count: Optional[int] = None,
    rssi_dbm: Optional[float] = None,
    region: str = "UK/EU",
) -> SignalGuessResult:
    """
    Convenience function to guess signal type.

    See SignalGuessingEngine.guess_signal_type for full documentation.
    """
    engine = get_engine(region)
    return engine.guess_signal_type(
        frequency_hz=frequency_hz,
        modulation=modulation,
        bandwidth_hz=bandwidth_hz,
        duration_ms=duration_ms,
        repetition_count=repetition_count,
        rssi_dbm=rssi_dbm,
        region=region,
    )


def guess_signal_type_dict(
    frequency_hz: int,
    modulation: Optional[str] = None,
    bandwidth_hz: Optional[int] = None,
    duration_ms: Optional[int] = None,
    repetition_count: Optional[int] = None,
    rssi_dbm: Optional[float] = None,
    region: str = "UK/EU",
) -> dict:
    """
    Convenience function returning dict (for JSON serialization).
    """
    result = guess_signal_type(
        frequency_hz=frequency_hz,
        modulation=modulation,
        bandwidth_hz=bandwidth_hz,
        duration_ms=duration_ms,
        repetition_count=repetition_count,
        rssi_dbm=rssi_dbm,
        region=region,
    )

    return {
        "primary_label": result.primary_label,
        "confidence": result.confidence.value,
        "alternatives": [
            {
                "label": alt.label,
                "confidence": alt.confidence.value,
            }
            for alt in result.alternatives
        ],
        "explanation": result.explanation,
        "tags": result.tags,
    }
