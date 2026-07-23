"""PII / secret redaction and prompt-injection heuristics.

Runs at ingress (before any text reaches the model or a persisted transcript).
We deliberately keep email/usernames intact (operationally required to action IT
tickets and low-sensitivity here) while scrubbing high-risk secrets: passwords,
API keys/tokens, card numbers, and national IDs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# (compiled pattern, replacement)
_REDACTIONS: list[tuple[re.Pattern[str], str]] = [
    # "password is hunter2", "pwd: x", "pass = y", "passcode - z"
    (
        re.compile(r"(?i)\b(pass(?:word|code|phrase)?|pwd)\b\s*(?:is|:|=|-)?\s*\S+"),
        r"\1: [REDACTED_SECRET]",
    ),
    # bearer / api tokens
    (re.compile(r"(?i)\b(bearer|token|api[_-]?key|secret)\b\s*[:=]?\s*\S+"), r"\1: [REDACTED_SECRET]"),
    # long high-entropy hex / base64-ish strings (>= 24 chars)
    (re.compile(r"\b[A-Za-z0-9+/_-]{24,}={0,2}\b"), "[REDACTED_TOKEN]"),
    # credit-card-like 13-16 digit groups
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "[REDACTED_CARD]"),
    # US SSN
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    # phone numbers (optional country code, then 3-3-4 groups)
    (
        re.compile(r"(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b"),
        "[REDACTED_PHONE]",
    ),
]

# Prompt-injection / jailbreak signal phrases.
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)ignore (all |your |previous |above )?instructions"),
    re.compile(r"(?i)disregard (the |your |all )?(previous|above|prior)"),
    re.compile(r"(?i)you are now\b"),
    re.compile(r"(?i)\bsystem prompt\b"),
    re.compile(r"(?i)act as (an? )?(admin|root|developer|dan)\b"),
    re.compile(r"(?i)reveal( your)? (instructions|prompt|rules)"),
    re.compile(r"(?i)pretend (to be|you are)"),
    re.compile(r"(?i)override (the )?(policy|policies|safety|rules)"),
    re.compile(r"(?i)\bjailbreak\b"),
]


@dataclass
class RedactionReport:
    text: str
    redaction_count: int
    injection_suspected: bool


class RedactionService:
    def redact(self, text: str) -> str:
        if not text:
            return text
        out = text
        for pattern, replacement in _REDACTIONS:
            out = pattern.sub(replacement, out)
        return out

    def detect_injection(self, text: str) -> bool:
        return any(p.search(text or "") for p in _INJECTION_PATTERNS)

    def process(self, text: str) -> RedactionReport:
        """Redact and flag injection in one pass (injection detected on raw text)."""
        injection = self.detect_injection(text)
        count = sum(len(pattern.findall(text or "")) for pattern, _ in _REDACTIONS)
        redacted = self.redact(text)
        return RedactionReport(text=redacted, redaction_count=count, injection_suspected=injection)
