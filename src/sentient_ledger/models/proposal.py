"""Adjustment proposal and journal entry models."""

from decimal import Decimal

from pydantic import BaseModel

from sentient_ledger.models.enums import AgentId, AuthorityLevel, ProposalStatus


class JournalEntry(BaseModel):
    entry_id: str
    debit_account: str
    debit_amount: Decimal
    credit_account: str
    credit_amount: Decimal
    memo: str = ""
    effective_date: str = ""


class ReasoningStep(BaseModel):
    step_number: int
    action: str
    input_ref: str = ""
    output_summary: str = ""
    rule_applied: str | None = None
    confidence: float = 1.0


class TotalImpact(BaseModel):
    absolute: Decimal
    accounts_affected: int = 0
    entities_affected: list[str] = []


class RequiredApproval(BaseModel):
    authority_level: AuthorityLevel
    required_roles: list[str] = []
    sla_hours: float = 4.0
    escalation_path: list[str] = []


class ReasoningChain(BaseModel):
    trigger: dict = {}
    findings: dict = {}
    analysis: dict = {}
    logic_steps: list[ReasoningStep] = []
    confidence: float = 0.0
    alternative_actions: list[str] = []
    risk_assessment: str = ""


class AuditMetadata(BaseModel):
    source_data_checksums: list[str] = []
    agent_versions: dict[str, str] = {}


class AdjustmentProposal(BaseModel):
    proposal_id: str
    trace_id: str
    created_at: str
    created_by: AgentId
    status: ProposalStatus = ProposalStatus.PENDING_REVIEW
    journal_entries: list[JournalEntry]
    total_impact: TotalImpact
    reasoning_steps: list[ReasoningStep] = []
    confidence: float = 0.0
    required_approval: RequiredApproval = RequiredApproval(
        authority_level=AuthorityLevel.L1_STAFF
    )
    reasoning_chain: ReasoningChain | None = None
    audit_metadata: AuditMetadata | None = None
    rejection_context: str | None = None
