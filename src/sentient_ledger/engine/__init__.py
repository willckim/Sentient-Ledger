"""Engine package: depreciation calculator, error detector, and eval comparator."""

from sentient_ledger.engine.comparator import compare_results as evaluate_detection
from sentient_ledger.engine.depreciation import calculate_monthly_depreciation
from sentient_ledger.engine.detector import detect_errors

__all__ = [
    "detect_errors",
    "calculate_monthly_depreciation",
    "evaluate_detection",
]
