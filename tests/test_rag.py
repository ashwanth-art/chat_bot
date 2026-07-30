from app.rag import OUT_OF_SCOPE_MESSAGE, bundled_aci_corpus, bundled_aci_documents
from app.text_utils import (
    chunk_text,
    clean_answer_for_display,
    is_clearly_out_of_scope,
)


def test_chunk_text_empty():
    assert chunk_text("  \n ") == []


def test_chunk_text_overlaps_and_preserves_content():
    text = " ".join(f"word{i}" for i in range(300))
    chunks = chunk_text(text, size=200, overlap=30)
    assert len(chunks) > 1
    assert chunks[0].startswith("word0")
    assert chunks[-1].endswith("word299")


def test_bundled_aci_corpus_combines_all_sources():
    corpus = bundled_aci_corpus().decode("utf-8")
    assert corpus.count("retrieved_on:") == 13
    assert "Applied AI" in corpus
    assert "Healthcare" in corpus
    assert "Financial Services" in corpus
    assert "Loyalty with real-time customer intelligence" in corpus
    assert "PDS enterprise data-platform transformation" in corpus
    assert "Shift-left cybersecurity for medical devices" in corpus


def test_bundled_aci_documents_preserve_source_names():
    names = [name for name, _ in bundled_aci_documents()]
    assert len(names) == 13
    assert "12_service_catalog.md" in names
    assert "13_industry_catalog.md" in names
    assert len(names) == len(set(names))


def test_obvious_unrelated_questions_are_rejected():
    assert is_clearly_out_of_scope("What is tomorrow's weather in Mumbai?")
    assert is_clearly_out_of_scope("Tell me a joke")
    assert not is_clearly_out_of_scope("Does ACI provide retail forecasting services?")
    assert "ACI Infotech" in OUT_OF_SCOPE_MESSAGE


def test_answer_cleanup_removes_internal_sources_and_markdown():
    answer = (
        "ACI modernized the client's reporting. "
        "[source: 08_case_study_sap_finance_transformation.md#3]\n\n"
        "Sources: 08_case_study_sap_finance_transformation.md#3\n"
        "**This is a clear result.**"
    )
    cleaned = clean_answer_for_display(answer)
    assert cleaned == "ACI modernized the client's reporting.\nThis is a clear result."
    assert ".md" not in cleaned
    assert "[source:" not in cleaned
