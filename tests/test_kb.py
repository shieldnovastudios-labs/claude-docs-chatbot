from pathlib import Path

from kb import Chunk, KnowledgeBase, chunk_text, load_chunks, tokenize

DOCS = Path(__file__).resolve().parents[1] / "docs"


def test_tokenize_drops_stopwords_and_folds_plurals():
    assert tokenize("What are the PRICES for nails?") == ["price", "nail"]
    assert tokenize("cancel cancellations grooming") == ["cancel", "cancel", "groom"]


def test_chunking_splits_by_heading_and_keeps_heading():
    text = "# Title\n\nIntro line.\n\n## Hours\n\nOpen 9-5.\n\n## Parking\n\nBehind the shop."
    chunks = chunk_text(text, "info.md")
    assert [c.heading for c in chunks] == ["Title", "Hours", "Parking"]
    assert chunks[1].text == "Open 9-5."
    assert chunks[1].title == "info.md — Hours"


def test_chunking_splits_long_sections_on_paragraphs():
    paras = ["word " * 40 for _ in range(6)]  # ~200 chars each
    chunks = chunk_text("## Long\n\n" + "\n\n".join(paras), "long.md", max_chars=450)
    assert len(chunks) == 3
    assert all(c.heading == "Long" for c in chunks)
    assert all(len(c.text) <= 450 for c in chunks)


def test_text_without_headings_is_one_chunk():
    chunks = chunk_text("Just a note.\nSecond line.", "note.txt")
    assert chunks == [Chunk("note.txt", "", "Just a note.\nSecond line.")]


def test_sample_docs_load():
    chunks = load_chunks(DOCS)
    assert {c.source for c in chunks} >= {"faq.md", "opening-hours.md", "services-and-prices.md"}


def test_ranking_puts_the_right_document_first():
    kb = KnowledgeBase.from_folder(DOCS)
    cases = {
        "How much is a full groom for a large dog?": ("services-and-prices.md", "Full groom"),
        "Are you open on Saturday?": ("opening-hours.md", "Opening hours"),
        "Can I cancel my appointment?": ("booking-and-cancellation.md", "Cancellations and rescheduling"),
        "Which vaccinations does my dog need?": ("health-and-safety.md", "Vaccinations"),
        "Do you groom cats?": ("faq.md", "Do you groom cats?"),
    }
    for question, (source, heading) in cases.items():
        top = kb.search(question)[0][1]
        assert (top.source, top.heading) == (source, heading), question


def test_scores_are_sorted_and_top_k_respected():
    kb = KnowledgeBase.from_folder(DOCS)
    hits = kb.search("price groom dog nail bath", top_k=3)
    assert len(hits) == 3
    scores = [s for s, _ in hits]
    assert scores == sorted(scores, reverse=True)


def test_unrelated_question_finds_nothing():
    kb = KnowledgeBase.from_folder(DOCS)
    assert kb.search("What is the capital of France?") == []
    assert kb.search("the and of") == []
