from app.services.extractor import _normalize_atom


def test_normalize_atom_valid():
    raw = {
        "memory_type": "PREFERENCE",
        "category": "language",
        "subject": "user",
        "attribute": "language",
        "value": "Node.js",
        "content": "User prefers Node.js.",
        "priority": "high",
        "confidence_score": "0.87",
    }
    atom = _normalize_atom(raw)
    assert atom["memory_type"] == "PREFERENCE"
    assert atom["priority"] == "HIGH"
    assert atom["confidence_score"] == 0.87


def test_normalize_atom_rejects_missing_fields():
    assert _normalize_atom({"memory_type": "FACT"}) is None
    assert _normalize_atom({"memory_type": "FACT", "subject": "u", "attribute": "a"}) is None


def test_normalize_atom_rejects_bad_type():
    assert _normalize_atom({"memory_type": "WIZARD", "subject": "u",
                            "attribute": "a", "value": "v", "content": "c"}) is None
