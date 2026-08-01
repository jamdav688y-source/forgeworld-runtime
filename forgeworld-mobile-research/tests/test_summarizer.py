from summarizer import build_labeled_summary, extractive_summary, SUMMARY_LABEL


def test_empty_text_returns_empty():
    assert extractive_summary("") == ""
    assert build_labeled_summary("") == ""


def test_summary_is_labeled():
    text = "Agents coordinate through governance. Evidence must be preserved. Validation happens locally."
    labeled = build_labeled_summary(text)
    assert labeled.startswith(f"[{SUMMARY_LABEL}]")
