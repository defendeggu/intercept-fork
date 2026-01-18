"""
TSCM Report Generation Module

Generates:
1. Client-safe PDF reports with executive summary
2. Technical annex (JSON + CSV) with device timelines and indicators

DISCLAIMER: All reports include mandatory disclaimers.
No packet data. No claims of confirmed surveillance.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger('intercept.tscm.reports')

# =============================================================================
# Report Data Structures
# =============================================================================

@dataclass
class ReportFinding:
    """A single finding for the report."""
    identifier: str
    protocol: str
    name: Optional[str]
    risk_level: str
    risk_score: int
    description: str
    indicators: list[dict] = field(default_factory=list)
    recommended_action: str = ''
    playbook_reference: str = ''


@dataclass
class ReportMeetingSummary:
    """Meeting window summary for report."""
    name: Optional[str]
    start_time: str
    end_time: Optional[str]
    duration_minutes: float
    devices_first_seen: int
    behavior_changes: int
    high_interest_devices: int


@dataclass
class TSCMReport:
    """
    Complete TSCM sweep report.

    Contains all data needed for both client-safe PDF and technical annex.
    """
    # Report metadata
    report_id: str
    generated_at: datetime
    sweep_id: int
    sweep_type: str

    # Location and context
    location: Optional[str] = None
    baseline_id: Optional[int] = None
    baseline_name: Optional[str] = None

    # Executive summary
    executive_summary: str = ''
    overall_risk_assessment: str = 'low'  # low, moderate, elevated, high
    key_findings_count: int = 0

    # Capabilities used
    capabilities: dict = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)

    # Findings by risk tier
    high_interest_findings: list[ReportFinding] = field(default_factory=list)
    needs_review_findings: list[ReportFinding] = field(default_factory=list)
    informational_findings: list[ReportFinding] = field(default_factory=list)

    # Meeting window summaries
    meeting_summaries: list[ReportMeetingSummary] = field(default_factory=list)

    # Statistics
    total_devices_scanned: int = 0
    wifi_devices: int = 0
    bluetooth_devices: int = 0
    rf_signals: int = 0
    new_devices: int = 0
    missing_devices: int = 0

    # Sweep duration
    sweep_start: Optional[datetime] = None
    sweep_end: Optional[datetime] = None
    duration_minutes: float = 0.0

    # Technical data (for annex only)
    device_timelines: list[dict] = field(default_factory=list)
    all_indicators: list[dict] = field(default_factory=list)
    baseline_diff: Optional[dict] = None
    correlation_data: list[dict] = field(default_factory=list)


# =============================================================================
# Disclaimer Text
# =============================================================================

REPORT_DISCLAIMER = """
IMPORTANT DISCLAIMER

This report documents the findings of a Technical Surveillance Countermeasures
(TSCM) sweep conducted using electronic detection equipment. The following
limitations and considerations apply:

1. DETECTION LIMITATIONS: No TSCM sweep can guarantee detection of all
   surveillance devices. Sophisticated devices may evade detection.

2. FINDINGS ARE INDICATORS: All findings represent patterns and indicators,
   NOT confirmed surveillance devices. Each finding requires professional
   interpretation and may have legitimate explanations.

3. ENVIRONMENTAL FACTORS: Wireless signals are affected by building
   construction, interference, and other environmental factors that may
   impact detection accuracy.

4. POINT-IN-TIME ASSESSMENT: This report reflects conditions at the time
   of the sweep. Conditions may change after the assessment.

5. NOT LEGAL ADVICE: This report does not constitute legal advice. Consult
   qualified legal counsel for guidance on surveillance-related matters.

6. PRIVACY CONSIDERATIONS: Some detected devices may be legitimate personal
   devices of authorized individuals.

This report should be treated as confidential and distributed only to
authorized personnel on a need-to-know basis.
"""

ANNEX_DISCLAIMER = """
TECHNICAL ANNEX DISCLAIMER

This annex contains detailed technical data from the TSCM sweep. This data
is provided for documentation and audit purposes.

- No raw packet captures or intercepted communications are included
- Device identifiers (MAC addresses) are included for tracking purposes
- Signal strength values are approximate and environment-dependent
- Timeline data is time-bucketed to preserve privacy
- All interpretations require professional TSCM expertise

This data should be handled according to organizational data protection
policies and applicable privacy regulations.
"""


# =============================================================================
# Report Generation Functions
# =============================================================================

def generate_executive_summary(report: TSCMReport) -> str:
    """Generate executive summary text."""
    lines = []

    # Opening
    lines.append(f"TSCM Sweep Report - {report.location or 'Location Not Specified'}")
    lines.append(f"Conducted: {report.sweep_start.strftime('%Y-%m-%d %H:%M') if report.sweep_start else 'Unknown'}")
    lines.append(f"Duration: {report.duration_minutes:.0f} minutes")
    lines.append("")

    # Overall assessment
    assessment_text = {
        'low': 'No significant indicators of surveillance activity were detected.',
        'moderate': 'Some devices require review but no confirmed surveillance indicators.',
        'elevated': 'Multiple indicators warrant further investigation.',
        'high': 'Significant indicators detected requiring immediate attention.',
    }
    lines.append(f"OVERALL ASSESSMENT: {report.overall_risk_assessment.upper()}")
    lines.append(assessment_text.get(report.overall_risk_assessment, ''))
    lines.append("")

    # Key statistics
    lines.append("SCAN STATISTICS:")
    lines.append(f"  - Total devices scanned: {report.total_devices_scanned}")
    lines.append(f"    - WiFi access points: {report.wifi_devices}")
    lines.append(f"    - Bluetooth devices: {report.bluetooth_devices}")
    lines.append(f"    - RF signals: {report.rf_signals}")
    lines.append("")

    # Findings summary
    lines.append("FINDINGS SUMMARY:")
    lines.append(f"  - High Interest (require investigation): {len(report.high_interest_findings)}")
    lines.append(f"  - Needs Review: {len(report.needs_review_findings)}")
    lines.append(f"  - Informational: {len(report.informational_findings)}")
    lines.append("")

    # Baseline comparison if available
    if report.baseline_name:
        lines.append(f"BASELINE COMPARISON (vs '{report.baseline_name}'):")
        lines.append(f"  - New devices: {report.new_devices}")
        lines.append(f"  - Missing devices: {report.missing_devices}")
        lines.append("")

    # Meeting window summary if available
    if report.meeting_summaries:
        lines.append("MEETING WINDOW ACTIVITY:")
        for meeting in report.meeting_summaries:
            lines.append(f"  - {meeting.name or 'Unnamed meeting'}: "
                        f"{meeting.devices_first_seen} new devices, "
                        f"{meeting.high_interest_devices} high interest")
        lines.append("")

    # Limitations
    if report.limitations:
        lines.append("SWEEP LIMITATIONS:")
        for limit in report.limitations[:3]:  # Top 3 limitations
            lines.append(f"  - {limit}")
        lines.append("")

    return "\n".join(lines)


def generate_findings_section(findings: list[ReportFinding], title: str) -> str:
    """Generate a findings section for the report."""
    if not findings:
        return f"{title}\n\nNo findings in this category.\n"

    lines = [title, "=" * len(title), ""]

    for i, finding in enumerate(findings, 1):
        lines.append(f"{i}. {finding.name or finding.identifier}")
        lines.append(f"   Protocol: {finding.protocol.upper()}")
        lines.append(f"   Identifier: {finding.identifier}")
        lines.append(f"   Risk Score: {finding.risk_score}")
        lines.append(f"   Description: {finding.description}")
        if finding.indicators:
            lines.append("   Indicators:")
            for ind in finding.indicators[:5]:  # Limit to 5 indicators
                lines.append(f"     - {ind.get('type', 'unknown')}: {ind.get('description', '')}")
        lines.append(f"   Recommended Action: {finding.recommended_action}")
        if finding.playbook_reference:
            lines.append(f"   Reference: {finding.playbook_reference}")
        lines.append("")

    return "\n".join(lines)


def generate_meeting_section(summaries: list[ReportMeetingSummary]) -> str:
    """Generate meeting window summary section."""
    if not summaries:
        return "MEETING WINDOW SUMMARY\n\nNo meeting windows were marked during this sweep.\n"

    lines = ["MEETING WINDOW SUMMARY", "=" * 22, ""]

    for meeting in summaries:
        lines.append(f"Meeting: {meeting.name or 'Unnamed'}")
        lines.append(f"  Time: {meeting.start_time} - {meeting.end_time or 'ongoing'}")
        lines.append(f"  Duration: {meeting.duration_minutes:.0f} minutes")
        lines.append(f"  Devices first seen during meeting: {meeting.devices_first_seen}")
        lines.append(f"  Behavior changes detected: {meeting.behavior_changes}")
        lines.append(f"  High interest devices active: {meeting.high_interest_devices}")

        if meeting.devices_first_seen > 0 or meeting.high_interest_devices > 0:
            lines.append("  NOTE: Meeting-correlated activity detected - see findings for details")
        lines.append("")

    lines.append("Meeting-correlated activity indicates temporal correlation only.")
    lines.append("Devices appearing during meetings may have legitimate explanations.")
    lines.append("")

    return "\n".join(lines)


def generate_pdf_content(report: TSCMReport) -> str:
    """
    Generate complete PDF report content.

    Returns plain text that can be converted to PDF.
    For actual PDF generation, use a library like reportlab or weasyprint.
    """
    sections = []

    # Header
    sections.append("=" * 70)
    sections.append("TECHNICAL SURVEILLANCE COUNTERMEASURES (TSCM) SWEEP REPORT")
    sections.append("=" * 70)
    sections.append("")
    sections.append(f"Report ID: {report.report_id}")
    sections.append(f"Generated: {report.generated_at.strftime('%Y-%m-%d %H:%M:%S')}")
    sections.append(f"Sweep ID: {report.sweep_id}")
    sections.append("")

    # Executive Summary
    sections.append("-" * 70)
    sections.append("EXECUTIVE SUMMARY")
    sections.append("-" * 70)
    sections.append(report.executive_summary or generate_executive_summary(report))
    sections.append("")

    # High Interest Findings
    if report.high_interest_findings:
        sections.append("-" * 70)
        sections.append(generate_findings_section(
            report.high_interest_findings,
            "HIGH INTEREST FINDINGS"
        ))

    # Needs Review Findings
    if report.needs_review_findings:
        sections.append("-" * 70)
        sections.append(generate_findings_section(
            report.needs_review_findings,
            "FINDINGS REQUIRING REVIEW"
        ))

    # Meeting Window Summary
    if report.meeting_summaries:
        sections.append("-" * 70)
        sections.append(generate_meeting_section(report.meeting_summaries))

    # Capabilities & Limitations
    sections.append("-" * 70)
    sections.append("SWEEP CAPABILITIES & LIMITATIONS")
    sections.append("=" * 33)
    sections.append("")

    if report.capabilities:
        caps = report.capabilities
        sections.append("Equipment Used:")
        if caps.get('wifi', {}).get('mode') != 'unavailable':
            sections.append(f"  - WiFi: {caps.get('wifi', {}).get('mode', 'unknown')} mode")
        if caps.get('bluetooth', {}).get('mode') != 'unavailable':
            sections.append(f"  - Bluetooth: {caps.get('bluetooth', {}).get('mode', 'unknown')}")
        if caps.get('rf', {}).get('available'):
            sections.append(f"  - RF/SDR: {caps.get('rf', {}).get('device_type', 'unknown')}")
        sections.append("")

    if report.limitations:
        sections.append("Limitations:")
        for limit in report.limitations:
            sections.append(f"  - {limit}")
        sections.append("")

    # Disclaimer
    sections.append("-" * 70)
    sections.append(REPORT_DISCLAIMER)

    # Footer
    sections.append("")
    sections.append("=" * 70)
    sections.append("END OF REPORT")
    sections.append("=" * 70)

    return "\n".join(sections)


def generate_technical_annex_json(report: TSCMReport) -> dict:
    """
    Generate technical annex as JSON.

    Contains detailed device timelines, all indicators, and raw data
    for audit and further analysis.
    """
    return {
        'annex_type': 'tscm_technical_annex',
        'report_id': report.report_id,
        'generated_at': report.generated_at.isoformat(),
        'sweep_id': report.sweep_id,
        'disclaimer': ANNEX_DISCLAIMER.strip(),

        'sweep_details': {
            'type': report.sweep_type,
            'location': report.location,
            'start_time': report.sweep_start.isoformat() if report.sweep_start else None,
            'end_time': report.sweep_end.isoformat() if report.sweep_end else None,
            'duration_minutes': report.duration_minutes,
            'baseline_id': report.baseline_id,
            'baseline_name': report.baseline_name,
        },

        'capabilities': report.capabilities,
        'limitations': report.limitations,

        'statistics': {
            'total_devices': report.total_devices_scanned,
            'wifi_devices': report.wifi_devices,
            'bluetooth_devices': report.bluetooth_devices,
            'rf_signals': report.rf_signals,
            'new_devices': report.new_devices,
            'missing_devices': report.missing_devices,
            'high_interest_count': len(report.high_interest_findings),
            'needs_review_count': len(report.needs_review_findings),
            'informational_count': len(report.informational_findings),
        },

        'findings': {
            'high_interest': [
                {
                    'identifier': f.identifier,
                    'protocol': f.protocol,
                    'name': f.name,
                    'risk_score': f.risk_score,
                    'description': f.description,
                    'indicators': f.indicators,
                    'recommended_action': f.recommended_action,
                }
                for f in report.high_interest_findings
            ],
            'needs_review': [
                {
                    'identifier': f.identifier,
                    'protocol': f.protocol,
                    'name': f.name,
                    'risk_score': f.risk_score,
                    'description': f.description,
                    'indicators': f.indicators,
                }
                for f in report.needs_review_findings
            ],
        },

        'meeting_windows': [
            {
                'name': m.name,
                'start_time': m.start_time,
                'end_time': m.end_time,
                'duration_minutes': m.duration_minutes,
                'devices_first_seen': m.devices_first_seen,
                'behavior_changes': m.behavior_changes,
                'high_interest_devices': m.high_interest_devices,
            }
            for m in report.meeting_summaries
        ],

        'device_timelines': report.device_timelines,
        'all_indicators': report.all_indicators,
        'baseline_diff': report.baseline_diff,
        'correlations': report.correlation_data,
    }


def generate_technical_annex_csv(report: TSCMReport) -> str:
    """
    Generate device timeline data as CSV.

    Provides spreadsheet-compatible format for further analysis.
    """
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        'identifier',
        'protocol',
        'name',
        'risk_level',
        'risk_score',
        'first_seen',
        'last_seen',
        'observation_count',
        'rssi_min',
        'rssi_max',
        'rssi_mean',
        'rssi_stability',
        'movement_pattern',
        'meeting_correlated',
        'indicators',
    ])

    # Device data from timelines
    for timeline in report.device_timelines:
        indicators_str = '; '.join(
            f"{i.get('type', '')}({i.get('score', 0)})"
            for i in timeline.get('indicators', [])
        )

        signal = timeline.get('signal', {})
        metrics = timeline.get('metrics', {})
        movement = timeline.get('movement', {})
        meeting = timeline.get('meeting_correlation', {})

        writer.writerow([
            timeline.get('identifier', ''),
            timeline.get('protocol', ''),
            timeline.get('name', ''),
            timeline.get('risk_level', 'informational'),
            timeline.get('risk_score', 0),
            metrics.get('first_seen', ''),
            metrics.get('last_seen', ''),
            metrics.get('total_observations', 0),
            signal.get('rssi_min', ''),
            signal.get('rssi_max', ''),
            signal.get('rssi_mean', ''),
            signal.get('stability', ''),
            movement.get('pattern', ''),
            meeting.get('correlated', False),
            indicators_str,
        ])

    # Also add findings summary
    writer.writerow([])
    writer.writerow(['--- FINDINGS SUMMARY ---'])
    writer.writerow(['identifier', 'protocol', 'risk_level', 'risk_score', 'description', 'recommended_action'])

    all_findings = (
        report.high_interest_findings +
        report.needs_review_findings
    )

    for finding in all_findings:
        writer.writerow([
            finding.identifier,
            finding.protocol,
            finding.risk_level,
            finding.risk_score,
            finding.description,
            finding.recommended_action,
        ])

    return output.getvalue()


# =============================================================================
# Report Builder
# =============================================================================

class TSCMReportBuilder:
    """
    Builder for constructing TSCM reports from sweep data.

    Usage:
        builder = TSCMReportBuilder(sweep_id=123)
        builder.set_location("Conference Room A")
        builder.add_capabilities(capabilities_dict)
        builder.add_finding(finding)
        report = builder.build()
    """

    def __init__(self, sweep_id: int):
        self.sweep_id = sweep_id
        self.report = TSCMReport(
            report_id=f"TSCM-{sweep_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            generated_at=datetime.now(),
            sweep_id=sweep_id,
            sweep_type='standard',
        )

    def set_sweep_type(self, sweep_type: str) -> 'TSCMReportBuilder':
        self.report.sweep_type = sweep_type
        return self

    def set_location(self, location: str) -> 'TSCMReportBuilder':
        self.report.location = location
        return self

    def set_baseline(self, baseline_id: int, baseline_name: str) -> 'TSCMReportBuilder':
        self.report.baseline_id = baseline_id
        self.report.baseline_name = baseline_name
        return self

    def set_sweep_times(
        self,
        start: datetime,
        end: Optional[datetime] = None
    ) -> 'TSCMReportBuilder':
        self.report.sweep_start = start
        self.report.sweep_end = end or datetime.now()
        self.report.duration_minutes = (
            (self.report.sweep_end - self.report.sweep_start).total_seconds() / 60
        )
        return self

    def add_capabilities(self, capabilities: dict) -> 'TSCMReportBuilder':
        self.report.capabilities = capabilities
        self.report.limitations = capabilities.get('all_limitations', [])
        return self

    def add_finding(self, finding: ReportFinding) -> 'TSCMReportBuilder':
        if finding.risk_level == 'high_interest':
            self.report.high_interest_findings.append(finding)
        elif finding.risk_level in ['review', 'needs_review']:
            self.report.needs_review_findings.append(finding)
        else:
            self.report.informational_findings.append(finding)
        return self

    def add_findings_from_profiles(self, profiles: list[dict]) -> 'TSCMReportBuilder':
        """Add findings from correlation engine device profiles."""
        for profile in profiles:
            finding = ReportFinding(
                identifier=profile.get('identifier', ''),
                protocol=profile.get('protocol', ''),
                name=profile.get('name'),
                risk_level=profile.get('risk_level', 'informational'),
                risk_score=profile.get('total_score', 0),
                description=self._generate_finding_description(profile),
                indicators=profile.get('indicators', []),
                recommended_action=profile.get('recommended_action', 'monitor'),
                playbook_reference=self._get_playbook_reference(profile),
            )
            self.add_finding(finding)

        return self

    def _generate_finding_description(self, profile: dict) -> str:
        """Generate description from profile indicators."""
        indicators = profile.get('indicators', [])
        if not indicators:
            return f"{profile.get('protocol', 'Unknown').upper()} device detected"

        # Use first indicator as primary description
        primary = indicators[0]
        desc = primary.get('description', 'Pattern detected')

        if len(indicators) > 1:
            desc += f" (+{len(indicators) - 1} additional indicators)"

        return desc

    def _get_playbook_reference(self, profile: dict) -> str:
        """Get playbook reference based on profile."""
        risk_level = profile.get('risk_level', 'informational')
        indicators = profile.get('indicators', [])

        # Check for tracker
        tracker_types = ['airtag_detected', 'tile_detected', 'smarttag_detected', 'known_tracker']
        if any(i.get('type') in tracker_types for i in indicators):
            if risk_level == 'high_interest':
                return 'PB-001 (Tracker Detection)'

        if risk_level == 'high_interest':
            return 'PB-002 (Suspicious Device)'
        elif risk_level in ['review', 'needs_review']:
            return 'PB-003 (Unknown Device)'

        return ''

    def add_meeting_summary(self, summary: dict) -> 'TSCMReportBuilder':
        """Add meeting window summary."""
        meeting = ReportMeetingSummary(
            name=summary.get('name'),
            start_time=summary.get('start_time', ''),
            end_time=summary.get('end_time'),
            duration_minutes=summary.get('duration_minutes', 0),
            devices_first_seen=summary.get('devices_first_seen', 0),
            behavior_changes=summary.get('behavior_changes', 0),
            high_interest_devices=summary.get('high_interest_devices', 0),
        )
        self.report.meeting_summaries.append(meeting)
        return self

    def add_statistics(
        self,
        wifi: int = 0,
        bluetooth: int = 0,
        rf: int = 0,
        new: int = 0,
        missing: int = 0
    ) -> 'TSCMReportBuilder':
        self.report.wifi_devices = wifi
        self.report.bluetooth_devices = bluetooth
        self.report.rf_signals = rf
        self.report.total_devices_scanned = wifi + bluetooth + rf
        self.report.new_devices = new
        self.report.missing_devices = missing
        return self

    def add_device_timelines(self, timelines: list[dict]) -> 'TSCMReportBuilder':
        self.report.device_timelines = timelines
        return self

    def add_all_indicators(self, indicators: list[dict]) -> 'TSCMReportBuilder':
        self.report.all_indicators = indicators
        return self

    def add_baseline_diff(self, diff: dict) -> 'TSCMReportBuilder':
        self.report.baseline_diff = diff
        return self

    def add_correlations(self, correlations: list[dict]) -> 'TSCMReportBuilder':
        self.report.correlation_data = correlations
        return self

    def build(self) -> TSCMReport:
        """Build and return the complete report."""
        # Calculate overall risk assessment
        if self.report.high_interest_findings:
            if len(self.report.high_interest_findings) >= 3:
                self.report.overall_risk_assessment = 'high'
            else:
                self.report.overall_risk_assessment = 'elevated'
        elif self.report.needs_review_findings:
            self.report.overall_risk_assessment = 'moderate'
        else:
            self.report.overall_risk_assessment = 'low'

        self.report.key_findings_count = (
            len(self.report.high_interest_findings) +
            len(self.report.needs_review_findings)
        )

        # Generate executive summary
        self.report.executive_summary = generate_executive_summary(self.report)

        return self.report


# =============================================================================
# Report Generation API Functions
# =============================================================================

def generate_report(
    sweep_id: int,
    sweep_data: dict,
    device_profiles: list[dict],
    capabilities: dict,
    timelines: list[dict],
    baseline_diff: Optional[dict] = None,
    meeting_summaries: Optional[list[dict]] = None,
    correlations: Optional[list[dict]] = None,
) -> TSCMReport:
    """
    Generate a complete TSCM report from sweep data.

    Args:
        sweep_id: Sweep ID
        sweep_data: Sweep dict from database
        device_profiles: List of DeviceProfile dicts from correlation engine
        capabilities: Capabilities dict
        timelines: Device timeline dicts
        baseline_diff: Optional baseline diff dict
        meeting_summaries: Optional meeting summaries
        correlations: Optional correlation data

    Returns:
        Complete TSCMReport
    """
    builder = TSCMReportBuilder(sweep_id)

    # Basic info
    builder.set_sweep_type(sweep_data.get('sweep_type', 'standard'))

    # Parse times
    started_at = sweep_data.get('started_at')
    completed_at = sweep_data.get('completed_at')
    if started_at:
        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at.replace('Z', '+00:00')).replace(tzinfo=None)
        if completed_at:
            if isinstance(completed_at, str):
                completed_at = datetime.fromisoformat(completed_at.replace('Z', '+00:00')).replace(tzinfo=None)
        builder.set_sweep_times(started_at, completed_at)

    # Capabilities
    builder.add_capabilities(capabilities)

    # Add findings from profiles
    builder.add_findings_from_profiles(device_profiles)

    # Statistics
    results = sweep_data.get('results', {})
    builder.add_statistics(
        wifi=len(results.get('wifi', [])),
        bluetooth=len(results.get('bluetooth', [])),
        rf=len(results.get('rf', [])),
        new=baseline_diff.get('summary', {}).get('new_devices', 0) if baseline_diff else 0,
        missing=baseline_diff.get('summary', {}).get('missing_devices', 0) if baseline_diff else 0,
    )

    # Technical data
    builder.add_device_timelines(timelines)

    if baseline_diff:
        builder.add_baseline_diff(baseline_diff)

    if meeting_summaries:
        for summary in meeting_summaries:
            builder.add_meeting_summary(summary)

    if correlations:
        builder.add_correlations(correlations)

    # Extract all indicators
    all_indicators = []
    for profile in device_profiles:
        for ind in profile.get('indicators', []):
            all_indicators.append({
                'device': profile.get('identifier'),
                'protocol': profile.get('protocol'),
                **ind
            })
    builder.add_all_indicators(all_indicators)

    return builder.build()


def get_pdf_report(report: TSCMReport) -> str:
    """Get PDF-ready report content."""
    return generate_pdf_content(report)


def get_json_annex(report: TSCMReport) -> dict:
    """Get JSON technical annex."""
    return generate_technical_annex_json(report)


def get_csv_annex(report: TSCMReport) -> str:
    """Get CSV technical annex."""
    return generate_technical_annex_csv(report)
