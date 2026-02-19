"""Compliance scan result models."""

from pydantic import BaseModel


class ControlPointResult(BaseModel):
    control_id: str
    description: str
    passed: bool
    detail: str = ""


class ComplianceScanResult(BaseModel):
    scan_id: str
    timestamp: str
    entity_id: str = ""
    control_points: list[ControlPointResult]
    asset_flags: list[str] = []
    passed: bool = True
    summary: str = ""
