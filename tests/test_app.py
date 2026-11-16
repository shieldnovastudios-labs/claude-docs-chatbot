from fastapi.testclient import TestClient

from app import RateLimiter, create_app
from bot import Answer, Source


class StubBot:
    def __init__(self):
        self.questions = []

    def ask(self, question):
        self.questions.append(question)
        return Answer("We open at 9:00 am on Saturday.", [Source("opening-hours.md", "Opening hours", "Saturday")])


def test_ask_endpoint_returns_answer_and_sources():
    client = TestClient(create_app(bot=StubBot(), limiter=RateLimiter(10)))
    res = client.post("/ask", json={"question": "Open Saturday?"})
    assert res.status_code == 200
    body = res.json()
    assert body["sources"][0]["document"] == "opening-hours.md"
    assert body["refused"] is False


def test_question_too_long_is_rejected():
    bot = StubBot()
    client = TestClient(create_app(bot=bot, limiter=RateLimiter(10)))
    assert client.post("/ask", json={"question": "x" * 501}).status_code == 422
    assert client.post("/ask", json={"question": "   "}).status_code == 422
    assert bot.questions == []


def test_rate_limit_per_ip():
    client = TestClient(create_app(bot=StubBot(), limiter=RateLimiter(2)))
    codes = [client.post("/ask", json={"question": "hours?"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_rate_limiter_window_expires():
    limiter = RateLimiter(1, window=60)
    assert limiter.allow("1.2.3.4", now=0)
    assert not limiter.allow("1.2.3.4", now=30)
    assert limiter.allow("1.2.3.4", now=61)
    assert limiter.allow("5.6.7.8", now=30)


def test_widget_page_is_served():
    client = TestClient(create_app(bot=StubBot(), limiter=RateLimiter(10)))
    res = client.get("/")
    assert res.status_code == 200 and 'id="cw-panel"' in res.text
