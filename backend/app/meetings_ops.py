"""Shared meeting-finalization logic — used by the manual `/end` endpoint AND the
auto-pilot watcher, so ending a call always produces the same summary + CRM automation
(and, optionally, the rep coaching scorecard).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .actions import service as action_service
from .agent import coaching, planner
from .connectors import live_sources
from .integrations import hubspot
from .knowledge.store import index
from .models import (
    AuditLog,
    Intent,
    Meeting,
    MeetingScorecard,
    MeetingSummary,
    Suggestion,
    TranscriptSegment,
)
from .packs.registry import get_pack, pack_for_owner
from .realtime.manager import manager

log = logging.getLogger("copilot.finalize")


async def finalize_meeting(db: Session, meeting: Meeting, *, with_scorecard: bool = False) -> MeetingSummary:
    """End the meeting: generate the summary, propose CRM automation, broadcast, and
    (optionally) generate the rep scorecard. Idempotent — re-running won't re-propose actions."""
    meeting_id = meeting.id
    already_ended = meeting.status == "ended"
    meeting.status = "ended"
    meeting.ended_at = meeting.ended_at or datetime.now(timezone.utc)
    db.commit()

    segments = list(
        db.scalars(
            select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id).order_by(TranscriptSegment.ts)
        )
    )
    transcript_text = "\n".join(f"{s.speaker} ({s.role}): {s.text}" for s in segments)
    intent_rows = list(db.scalars(select(Intent).where(Intent.meeting_id == meeting_id)))
    suggestion_rows = list(db.scalars(select(Suggestion).where(Suggestion.meeting_id == meeting_id)))
    crm = hubspot.company_context(db, meeting.crm_company_id)

    # Prior conversations with this same client (by CRM company, else by name).
    client_filters = []
    if meeting.crm_company_id:
        client_filters.append(Meeting.crm_company_id == meeting.crm_company_id)
    if meeting.customer_company:
        client_filters.append(Meeting.customer_company == meeting.customer_company)
    history: list[dict] = []
    if client_filters:
        for pm in db.scalars(
            select(Meeting)
            .where(Meeting.id != meeting_id, Meeting.status == "ended", or_(*client_filters))
            .order_by(Meeting.created_at.desc()).limit(5)
        ).all():
            ps = db.scalar(select(MeetingSummary).where(MeetingSummary.meeting_id == pm.id))
            history.append({
                "date": pm.created_at.strftime("%Y-%m-%d") if pm.created_at else "",
                "title": pm.title,
                "summary": ps.executive_summary if ps else "",
                "decisions": ps.key_decisions if ps else [],
                "open_actions": ps.action_items if ps else [],
            })

    topics = " ".join(sorted({i.intent_type for i in intent_rows if i.intent_type != "general"}))
    docs = [
        {"title": h.title, "snippet": h.snippet}
        for h in await index.search(f"{meeting.customer_company} {topics}".strip(), k=4)
    ]

    # Frame the whole wrap-up (summary, actions, scorecard) by the OWNER's current team.
    pack_key = pack_for_owner(db, meeting)
    if meeting.pack != pack_key:
        meeting.pack = pack_key
    persona = "tech" if pack_key == "tech" else "sales"

    # Pull the owner's own Gmail/Drive/Slack content around this account/topic so the recap can
    # connect the call to what's happening across their connected sources (not just the transcript).
    comms = []
    if meeting.owner_user_id:
        q = " ".join(x for x in [meeting.customer_company or "", topics] if x).strip()
        comms = await live_sources.gather_comms(db, meeting.owner_user_id, q, read_bodies=True)

    summary_data = await get_pack(pack_key).summarize(
        meeting={"customer_company": meeting.customer_company, "customer_contact": meeting.customer_contact, "rep_name": meeting.rep_name},
        intents=[{"intent_type": i.intent_type} for i in intent_rows],
        suggestions=[{"actions": s.actions, "answer": s.answer} for s in suggestion_rows],
        crm=crm, transcript=transcript_text, history=history, docs=docs, persona=persona, comms=comms,
    )

    summary = db.scalar(select(MeetingSummary).where(MeetingSummary.meeting_id == meeting_id)) or MeetingSummary(meeting_id=meeting_id)
    summary.executive_summary = summary_data["executive_summary"]
    summary.key_decisions = summary_data["key_decisions"]
    summary.risks = summary_data["risks"]
    summary.action_items = summary_data["action_items"]
    summary.customer_concerns = summary_data["customer_concerns"]
    summary.follow_up_email = summary_data["follow_up_email"]
    db.add(summary)
    db.commit()

    if not already_ended:
        note_body = (
            summary_data["executive_summary"]
            + "\n\nKey decisions:\n- " + "\n- ".join(summary_data["key_decisions"])
            + "\n\nRisks:\n- " + "\n- ".join(summary_data["risks"])
        )
        action_service.propose(db, meeting_id=meeting_id, pack=pack_key, action_key="create_note",
                               kind="note", title="Log meeting recap note to CRM", payload={"body": note_body})

        # ── Agentic plan: typed, executable next actions (Jira tickets, researched Notion
        #    docs, reminders…) the user approves, then the agent performs for real. ──────
        try:
            planned = await planner.plan_actions(
                transcript=transcript_text, summary_data=summary_data, persona=persona
            )
        except Exception as exc:  # pragma: no cover
            log.warning("planner failed for %s: %s", meeting_id, exc)
            planned = []
        if planned:
            for a in planned:
                action_service.propose(db, meeting_id=meeting_id, pack=meeting.pack,
                                       action_key=a["action_key"], kind=a["kind"],
                                       title=a["title"], payload=a["payload"])
        else:  # fallback to plain tasks if the planner is unavailable
            for item in summary_data["action_items"][:6]:
                if "recap email" in item.lower():
                    continue
                action_service.propose(db, meeting_id=meeting_id, pack=meeting.pack, action_key="create_task",
                                       kind="task", title=item, payload={"title": item})

        action_service.propose(db, meeting_id=meeting_id, pack=meeting.pack, action_key="send_email",
                               kind="email", title="Send follow-up email to customer",
                               payload={"draft": summary_data["follow_up_email"]})
        db.add(AuditLog(actor="copilot", action="meeting.ended", resource=meeting_id))
        db.commit()

    await manager.broadcast(meeting_id, {"type": "summary", "data": summary_data})
    await manager.broadcast(meeting_id, {"type": "status", "data": {"status": "ended"}})
    await manager.broadcast(meeting_id, {"type": "crm_sync", "data": {"synced": True}})

    if with_scorecard and not db.scalar(select(MeetingScorecard).where(MeetingScorecard.meeting_id == meeting_id)):
        try:
            sc_data = await coaching.generate_scorecard(
                {"rep_name": meeting.rep_name, "customer_company": meeting.customer_company, "customer_contact": meeting.customer_contact},
                [{"speaker": s.speaker, "text": s.text, "role": s.role} for s in segments],
                transcript_text, persona=persona,
            )
            if sc_data:
                db.add(MeetingScorecard(
                    meeting_id=meeting_id, rep_name=sc_data["rep_name"], overall_score=sc_data["overall_score"],
                    headline=sc_data["headline"], dimensions=sc_data["dimensions"], strengths=sc_data["strengths"],
                    improvements=sc_data["improvements"], coaching_tips=sc_data["coaching_tips"], metrics=sc_data["metrics"],
                ))
                db.commit()
        except Exception as exc:  # pragma: no cover
            log.warning("auto-scorecard failed for %s: %s", meeting_id, exc)

    return summary
