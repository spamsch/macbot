"""Domain tagging for memory items.

Maps free text (a turn goal, a stored memory) to a coarse domain via
word-boundary keyword matching — the same ``\\b``-anchored approach used by
``core/routing.py`` so a substring like "pay" in "paperless" can't false-match.

Used to (1) tag each captured turn with a domain and (2) score which semantic
memories are relevant to the current turn so recall stays scoped ("help me with
finances" surfaces finance memories, not the whole store).
"""

import re

# Coarse domains aligned with the repo's existing skill areas. A single piece of
# text can match several domains; callers decide whether to keep all matches
# (scoring) or collapse to the strongest one (tagging).
DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "finances": [
        "finance", "finances", "financial", "money", "budget", "invoice",
        "invoices", "rechnung", "rechnungen", "payment", "sepa", "iban",
        "bank", "banking", "transfer", "überweisung", "tax", "taxes", "steuer",
        "expense", "expenses", "salary", "cost", "costs", "euro", "girocode",
    ],
    "mail": [
        "mail", "email", "emails", "inbox", "unread", "reply", "replies",
        "sender", "attachment", "attachments", "imap",
    ],
    "calendar": [
        "calendar", "event", "events", "meeting", "meetings", "appointment",
        "appointments", "schedule", "reminder", "reminders", "deadline",
    ],
    "documents": [
        "document", "documents", "paperless", "pdf", "scan", "scanned",
        "tagging", "beihilfe", "archive", "filing",
    ],
    "health": [
        "health", "pkv", "debeka", "leistungsbescheid", "leistungsmitteilung",
        "doctor", "medical", "insurance", "krankenversicherung", "arzt",
    ],
    "travel": [
        "travel", "trip", "flight", "flights", "hotel", "hotels", "booking",
        "train", "vacation", "holiday", "itinerary",
    ],
    "coding": [
        "code", "coding", "bug", "function", "repository", "repo", "git",
        "commit", "test", "tests", "deploy", "python", "script", "api",
    ],
    "contacts": [
        "contact", "contacts", "phone", "address",
    ],
}


def _word_in(word: str, text_lower: str) -> bool:
    """True if ``word`` occurs as a whole word in already-lowercased text."""
    return re.search(rf"\b{re.escape(word)}\b", text_lower) is not None


def score_domains(text: str) -> dict[str, int]:
    """Return ``{domain: keyword_hit_count}`` for every domain with >=1 hit."""
    if not text:
        return {}
    low = text.lower()
    scores: dict[str, int] = {}
    for domain, words in DOMAIN_KEYWORDS.items():
        hits = sum(1 for w in words if _word_in(w, low))
        if hits:
            scores[domain] = hits
    return scores


def tag_domain(text: str) -> str:
    """Return the single best-matching domain for ``text``, or ``"general"``."""
    scores = score_domains(text)
    if not scores:
        return "general"
    # Highest hit count wins; ties broken by DOMAIN_KEYWORDS insertion order.
    return max(scores, key=lambda d: scores[d])
