from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from bot import REFUSAL, SYSTEM_PROMPT, DocsBot
from kb import KnowledgeBase

DOCS = Path(__file__).resolve().parents[1] / "docs"


def fake_response(blocks, stop_reason="end_turn"):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


def text_block(text, citations=None):
    return SimpleNamespace(type="text", text=text, citations=citations)


def citation(index, quote):
    return SimpleNamespace(type="char_location", document_index=index, cited_text=quote, document_title="x")


def make_bot(response=None):
    client = MagicMock()
    client.beta.messages.create.return_value = response
    return DocsBot(KnowledgeBase.from_folder(DOCS), client=client), client


def test_no_relevant_docs_refuses_without_calling_the_api():
    bot, client = make_bot()
    answer = bot.ask("What is the capital of France?")
    assert answer.refused and answer.text == REFUSAL and answer.sources == []
    client.beta.messages.create.assert_not_called()


def test_grounded_answer_returns_sources_from_citations():
    response = fake_response([
        SimpleNamespace(type="thinking", thinking=""),
        text_block("A full groom for a large dog is "),
        text_block("$90 (sample price)", [citation(0, "Large dogs (over 25 kg): $90 (sample price)")]),
        text_block("."),
    ])
    bot, client = make_bot(response)
    answer = bot.ask("How much is a full groom for a large dog?")

    assert not answer.refused
    assert answer.text == "A full groom for a large dog is $90 (sample price)."
    assert [(s.document, s.section) for s in answer.sources] == [("services-and-prices.md", "Full groom")]

    kwargs = client.beta.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-opus-5-5"
    assert kwargs["system"][0]["text"] == SYSTEM_PROMPT
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    docs = [b for b in kwargs["messages"][0]["content"] if b["type"] == "document"]
    assert docs and all(d["citations"] == {"enabled": True} for d in docs)
    assert docs[0]["title"] == "services-and-prices.md — Full groom"
    assert kwargs["messages"][0]["content"][-1]["text"].endswith("large dog?")


def test_model_saying_it_does_not_know_is_a_refusal():
    bot, _ = make_bot(fake_response([text_block(REFUSAL)]))
    answer = bot.ask("Do you offer cat grooming on Mondays?")
    assert answer.refused and answer.sources == []


def test_uncited_answer_is_replaced_by_refusal():
    bot, _ = make_bot(fake_response([text_block("Sure, we open at 7 am every day!")]))
    answer = bot.ask("Are you open on Saturday?")
    assert answer.refused and answer.text == REFUSAL


def test_api_refusal_stop_reason_is_handled():
    bot, _ = make_bot(fake_response([], stop_reason="refusal"))
    assert bot.ask("Are you open on Saturday?").refused


def test_system_prompt_is_static():
    # Caching needs an identical prefix: no dates or per-request values.
    assert "{" not in SYSTEM_PROMPT and REFUSAL in SYSTEM_PROMPT
