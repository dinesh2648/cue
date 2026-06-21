"""Seed data: a faithful HubSpot-shaped CRM + Google-Drive-shaped knowledge base.

Demo scenario: our company "Atlas Cloud" is closing an expansion deal with the
customer "Northwind Trading" (contact: Sarah Chen, VP Engineering).
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import CRMObject, KnowledgeDoc

COMPANY_ID = "comp_northwind"

_CRM: list[dict] = [
    {
        "id": COMPANY_ID,
        "object_type": "company",
        "company_id": COMPANY_ID,
        "properties": {
            "name": "Northwind Trading",
            "domain": "northwind.example.com",
            "industry": "Logistics & Distribution",
            "employees": 1800,
            "health": "Yellow — strong intent, a few open support issues",
            "arr": "120000",
        },
    },
    {
        "id": "contact_sarah",
        "object_type": "contact",
        "company_id": COMPANY_ID,
        "properties": {
            "name": "Sarah Chen",
            "title": "VP Engineering",
            "email": "sarah.chen@northwind.example.com",
            "role": "Economic buyer / champion",
        },
    },
    {
        "id": "deal_expansion",
        "object_type": "deal",
        "company_id": COMPANY_ID,
        "properties": {
            "dealname": "Northwind — Platform Expansion",
            "dealstage": "Contract Sent",
            "amount": "120000",
            "closedate": "2026-07-15",
            "contract_status": "Sent for signature — awaiting customer countersignature",
            "implementation_status": "Ready to begin on contract signature",
            "go_live_date": "2026-08-01",
            "onboarding_owner": "Priya Nair, Implementation Lead",
            "security_questionnaire_status": "In progress — 80% complete, due back this week",
            "latest_proposal": "v3, dated 2026-06-10",
            "line_items": ["Platform Pro (250 seats)", "Premium Support", "SSO / SAML add-on"],
            "discount": "12% for annual prepay; up to 18% on a 3-year term",
            "renewal_date": "2027-08-01",
            "arr": "120000",
        },
    },
    {
        "id": "ticket_sso",
        "object_type": "ticket",
        "company_id": COMPANY_ID,
        "properties": {
            "id": "T-1042",
            "subject": "SSO login intermittent for a subset of users",
            "priority": "High",
            "status": "Open",
            "opened": "2026-06-09",
        },
    },
    {
        "id": "ticket_export",
        "object_type": "ticket",
        "company_id": COMPANY_ID,
        "properties": {
            "id": "T-1051",
            "subject": "CSV export times out on very large reports",
            "priority": "Medium",
            "status": "In Progress",
            "opened": "2026-06-14",
        },
    },
    {
        "id": "ticket_docs",
        "object_type": "ticket",
        "company_id": COMPANY_ID,
        "properties": {
            "id": "T-1009",
            "subject": "Clarification on onboarding documentation",
            "priority": "Low",
            "status": "Closed",
            "opened": "2026-05-20",
        },
    },
]


def _doc(id: str, title: str, doc_type: str, content: str, mime="application/pdf") -> dict:
    return {
        "id": id,
        "title": title,
        "doc_type": doc_type,
        "mime": mime,
        "url": f"https://drive.google.com/file/d/{id}/view",
        "content": content,
    }


_DOCS: list[dict] = [
    _doc(
        "doc_soc2",
        "Atlas Cloud SOC 2 Type II Report (2025)",
        "soc2",
        "Atlas Cloud is SOC 2 Type II certified. The most recent report covers the audit period "
        "January 1 to December 31, 2025 and was issued by an independent AICPA-accredited auditor. "
        "It covers the Security, Availability, and Confidentiality trust service criteria with zero "
        "exceptions noted. The full report is available to customers and prospects under NDA. Key "
        "controls include logical access controls, change management, encryption, continuous "
        "monitoring, and incident response.",
    ),
    _doc(
        "doc_sec_wp",
        "Atlas Cloud Security Whitepaper",
        "security_whitepaper",
        "All customer data is encrypted in transit with TLS 1.2+ and at rest with AES-256. Atlas Cloud "
        "supports configurable data residency in the US and EU regions. The platform is fully GDPR "
        "compliant, supports data processing agreements, and honors data subject access and deletion "
        "requests. Authentication supports SSO via SAML 2.0 and OIDC, with role-based access control "
        "(RBAC) and granular permissions. Third-party penetration tests are performed annually and "
        "vulnerability scans run continuously. PII can be redacted from logs and transcripts.",
    ),
    _doc(
        "doc_nda",
        "Mutual Non-Disclosure Agreement (Template)",
        "nda",
        "This mutual NDA governs the exchange of confidential information between Atlas Cloud and the "
        "counterparty, including security reports such as the SOC 2. Term of confidentiality is three "
        "years from disclosure. Standard carve-outs apply for information that is public, independently "
        "developed, or rightfully received from a third party.",
    ),
    _doc(
        "doc_impl",
        "Implementation Plan & Onboarding Timeline",
        "implementation_plan",
        "Standard implementation runs approximately four weeks across three phases. Phase 1 "
        "Provisioning (week 1): environment setup, SSO/SAML configuration, and admin onboarding. "
        "Phase 2 Integration (weeks 2-3): data migration, API integration, and configuration of "
        "workflows. Phase 3 UAT & Go-Live (week 4): user acceptance testing, training, and production "
        "cutover. Target go-live is four weeks after contract signature, owned by the assigned "
        "Implementation Lead.",
    ),
    _doc(
        "doc_msa",
        "Master Services Agreement (MSA)",
        "contract",
        "The Master Services Agreement sets out the terms of service, subscription term, payment "
        "terms (net 30), service levels, limitation of liability, and data protection obligations. The "
        "initial term is 12 months and renews automatically unless either party gives 60 days notice. "
        "The agreement requires signatures from authorized representatives of both Atlas Cloud and the "
        "customer.",
    ),
    _doc(
        "doc_proposal",
        "Northwind Expansion Proposal v3",
        "proposal",
        "This proposal covers Platform Pro for 250 seats, Premium Support, and the SSO/SAML add-on, "
        "totaling $120,000 annually. A 12% discount is applied for annual prepayment. Multi-year "
        "options are available: a 3-year commitment unlocks up to an 18% discount and locks pricing "
        "against future increases. Scope includes onboarding, a dedicated implementation lead, and "
        "quarterly business reviews.",
    ),
    _doc(
        "doc_pricing",
        "Atlas Cloud Pricing & Packaging",
        "pricing",
        "Atlas Cloud is priced per seat across three tiers: Starter, Pro, and Enterprise. Volume "
        "discounts begin at 100 seats. Annual prepayment earns a 12% discount; multi-year commitments "
        "earn up to 18%. Add-ons include Premium Support, SSO/SAML, and advanced analytics. Deal desk "
        "can structure custom commercial terms for strategic accounts.",
    ),
    _doc(
        "doc_arch",
        "Atlas Cloud Product Architecture Overview",
        "product_architecture",
        "Atlas Cloud is a multi-tenant cloud platform with a REST and webhook API, native integrations "
        "for major CRMs and identity providers, and horizontal scalability to millions of records. It "
        "offers SSO via SAML/OIDC, audit logging, and a 99.9% uptime SLA. The architecture separates "
        "compute and storage for elastic scaling and supports regional deployment for data residency.",
    ),
]


def seed_if_empty(db: Session) -> dict:
    """Idempotently load seed data. Returns counts."""
    crm_count = db.scalar(select(CRMObject).limit(1))
    if crm_count is None:
        for row in _CRM:
            db.add(CRMObject(source="mock", **row))
    doc_count = db.scalar(select(KnowledgeDoc).limit(1))
    if doc_count is None:
        for d in _DOCS:
            db.add(KnowledgeDoc(source="google_drive", **d))
    db.commit()
    return {
        "crm_objects": db.scalar(select(func.count()).select_from(CRMObject)),
        "knowledge_docs": db.scalar(select(func.count()).select_from(KnowledgeDoc)),
    }
