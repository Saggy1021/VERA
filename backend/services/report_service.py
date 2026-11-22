# FILE: backend/services/report_service.py
# Build report JSON from events

import json
from typing import Optional
from db import queries


async def build_report(session_id: str, candidate_id: str) -> Optional[dict]:
    """
    Build a report from malpractice events for a session/candidate.
    Returns the created report dict or None if no events exist.
    """
    events = await queries.get_session_events(session_id)

    # Filter events for this candidate
    candidate_events = [
        e for e in events
        if str(e["candidate_id"]) == candidate_id
    ]

    if not candidate_events:
        return None

    # Count events by severity
    event_count = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    for event in candidate_events:
        severity = event.get("severity", "low")
        if severity in event_count:
            event_count[severity] += 1

    # Build timeline (array of event summaries)
    timeline = []
    for event in candidate_events:
        timeline.append({
            "time": event["occurred_at"].isoformat() if event.get("occurred_at") else None,
            "type": event.get("event_type", ""),
            "severity": event.get("severity", ""),
            "description": event.get("description", ""),
            "risk_score": event.get("risk_score", 0),
            "gemini_verdict": event.get("gemini_verdict"),
            "screenshot_url": event.get("screenshot_url"),
        })

    # Compute overall integrity score (100 = clean, 0 = worst)
    # Weighted penalty: critical=15, high=8, medium=3, low=1
    total_penalty = (
        event_count["critical"] * 15 +
        event_count["high"] * 8 +
        event_count["medium"] * 3 +
        event_count["low"] * 1
    )
    overall_score = max(0, 100 - total_penalty)

    # Generate summary text
    total_events = sum(event_count.values())
    summary = (
        f"Session recorded {total_events} malpractice event(s): "
        f"{event_count['critical']} critical, {event_count['high']} high, "
        f"{event_count['medium']} medium, {event_count['low']} low. "
        f"Overall integrity score: {overall_score}/100."
    )

    # Create report in database
    report = await queries.create_report(
        session_id=session_id,
        candidate_id=candidate_id,
        overall_score=overall_score,
        summary=summary,
        event_count=event_count,
        timeline=timeline,
    )

    return report if report else None


async def generate_draft_report(db, session_id: str, candidate_id: str) -> None:
    """
    B10: Auto-generate a draft report when a session transitions to 'completed'.
    Called synchronously in the same request as the status update — report generation
    is a fast DB aggregation query, not an ML call.

    Idempotent: skips silently if a report already exists for this candidate/session.
    Draft reports have status='draft' until the proctor publishes or suppresses them.
    """
    try:
        # Check if report already exists — don't overwrite a published report
        existing = await queries.get_report(session_id=session_id, candidate_id=candidate_id)
        if existing:
            return  # already generated — skip

        await build_report(session_id=session_id, candidate_id=candidate_id)
    except Exception as exc:
        # Non-fatal: if report generation fails, the proctor can still generate manually
        import logging
        logging.getLogger(__name__).warning(
            "Draft report generation failed for candidate %s in session %s: %s",
            candidate_id, session_id, exc
        )

