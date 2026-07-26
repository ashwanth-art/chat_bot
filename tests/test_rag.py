from app.rag import bundled_aci_corpus
from app.text_utils import chunk_text


def test_chunk_text_empty():
    assert chunk_text("  \n ") == []


def test_chunk_text_overlaps_and_preserves_content():
    text = " ".join(f"word{i}" for i in range(300))
    chunks = chunk_text(text, size=200, overlap=30)
    assert len(chunks) > 1
    assert chunks[0].startswith("word0")
    assert chunks[-1].endswith("word299")


def test_bundled_aci_corpus_combines_all_six_sources():
    corpus = bundled_aci_corpus().decode("utf-8")
    assert corpus.count("retrieved_on:") == 6
    assert "Applied AI" in corpus
    assert "Healthcare" in corpus
    assert "Financial Services" in corpus
