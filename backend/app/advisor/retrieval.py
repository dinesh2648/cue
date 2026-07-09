"""Retrieval Orchestrator agent.

Given a question and the meeting, it decides WHICH sources are in play for this employee's role and
fetches only the relevant context: role-scoped remote-MCP servers (Jira/GitHub for engineering,
CRM for customer-facing), the in-process sources (Gmail/Drive/Slack/Notion/Calendar), the evolving
meeting state, and the always-on user+company preamble. One object, handed to the Advisory agent.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..connectors import live_sources
from ..models import Organization, User
from . import meeting_context
from .profiles import advisory_preamble
from .roles import filter_servers_for_role


@dataclass
class Retrieval:
    servers: list[dict] = field(default_factory=list)   # role-filtered remote-MCP servers
    comms: list[dict] = field(default_factory=list)      # in-process source hits (Gmail/Drive/Slack/Notion/Calendar)
    preamble: str = ""                                    # user + company advisory context
    meeting_state: str = ""                               # evolving meeting context block
    user: User | None = None

    @property
    def has_sources(self) -> bool:
        return bool(self.servers or self.comms)


async def gather(db: Session, meeting, query: str, servers: list[dict], *, read_bodies: bool = False) -> Retrieval:
    """Assemble everything the Advisory agent needs, scoped to the meeting owner's role."""
    uid = getattr(meeting, "owner_user_id", None)
    user = db.get(User, uid) if uid else None
    org = db.get(Organization, user.org_id) if user and user.org_id else None
    return Retrieval(
        servers=filter_servers_for_role(user, servers),
        comms=await live_sources.gather_comms(db, uid, query, read_bodies=read_bodies),
        preamble=advisory_preamble(user, org),
        meeting_state=meeting_context.render(meeting),
        user=user,
    )
