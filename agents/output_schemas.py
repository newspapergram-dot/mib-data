"""output_schemas.py — Contratti JSON per ogni confine tra agenti.

Ogni agente del Comitato (`orchestrator.py`) puo' comunicare SOLO producendo un
oggetto che rispetta lo schema del proprio stadio. Questo e' il meccanismo che
rende la comunicazione tra agenti "unilaterale": l'agente a valle riceve dati
strutturati e vincolati (enum, bool, numeri), mai testo libero persuasivo che
potrebbe fargli ereditare il bias/framing di chi lo ha preceduto.
"""

RESEARCHER_SCHEMA = {
    "type": "object",
    "required": ["ticker", "news_sentiment", "sentiment_score", "key_events", "earnings_call_flag"],
    "properties": {
        "ticker": {"type": "string"},
        "news_sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
        "sentiment_score": {"type": "number", "minimum": -1, "maximum": 1},
        "key_events": {"type": "array", "items": {"type": "string"}},
        "earnings_call_flag": {"type": "boolean"},
    },
    "additionalProperties": False,
}

COMPANY_ANALYST_SCHEMA = {
    "type": "object",
    "required": ["ticker", "verdict", "reasons", "debt_flag"],
    "properties": {
        "ticker": {"type": "string"},
        "verdict": {"type": "string", "enum": ["pass", "reject"]},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "debt_flag": {"type": "boolean"},
    },
    "additionalProperties": False,
}

TECHNICAL_ANALYST_SCHEMA = {
    "type": "object",
    "required": ["ticker", "verdict", "reasons", "setup_read", "candlestick_read"],
    "properties": {
        "ticker": {"type": "string"},
        "verdict": {"type": "string", "enum": ["favorable", "unfavorable"]},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "setup_read": {"type": "string"},
        "candlestick_read": {"type": "string"},
    },
    "additionalProperties": False,
}

FINANCE_GUY_SCHEMA = {
    "type": "object",
    "required": ["macro_regime", "sector_rotation_favorable", "notes"],
    "properties": {
        "macro_regime": {"type": "string"},
        "sector_rotation_favorable": {"type": "boolean"},
        "notes": {"type": "string"},
    },
    "additionalProperties": False,
}

AUDITOR_SCHEMA = {
    "type": "object",
    "required": ["approved", "stop_loss_pct", "risk_notes"],
    "properties": {
        "approved": {"type": "boolean"},
        "stop_loss_pct": {"type": "number", "minimum": 0, "maximum": 1},
        "risk_notes": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}

CEO_SCHEMA = {
    "type": "object",
    "required": ["ticker", "action", "rationale", "final_stop_loss_pct"],
    "properties": {
        "ticker": {"type": "string"},
        "action": {"type": "string", "enum": ["BUY", "SKIP"]},
        "rationale": {"type": "string"},
        "final_stop_loss_pct": {"type": ["number", "null"]},
    },
    "additionalProperties": False,
}

POST_MORTEM_SCHEMA = {
    "type": "object",
    "required": ["ticker", "root_cause", "new_guideline", "target_file"],
    "properties": {
        "ticker": {"type": "string"},
        "root_cause": {"type": "string"},
        "new_guideline": {"type": "string"},
        "target_file": {"type": "string", "enum": ["macro_guidelines.md", "post_mortem_registry.md"]},
    },
    "additionalProperties": False,
}
