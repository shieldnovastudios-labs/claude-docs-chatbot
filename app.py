"""Web server: POST /ask for the chat widget, GET / for the widget page.

Run:  uvicorn app:app --port 8000
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Deque, Dict, Optional

import anthropic
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from bot import DocsBot
from kb import KnowledgeBase

BASE_DIR = Path(__file__).resolve().parent
DOCS_DIR = Path(os.environ.get("DOCS_DIR", BASE_DIR / "docs"))
MAX_QUESTION_CHARS = int(os.environ.get("MAX_QUESTION_CHARS", "500"))
RATE_LIMIT = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "10"))

# Logs go to the console only, and never include the visitor's question.
log = logging.getLogger("docs-chatbot")


class RateLimiter:
    """At most `limit` requests per IP in a sliding 60-second window (in memory)."""

    def __init__(self, limit: int, window: float = 60.0):
        self.limit, self.window = limit, window
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, now: Optional[float] = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=MAX_QUESTION_CHARS)


def create_app(bot: Optional[DocsBot] = None, limiter: Optional[RateLimiter] = None) -> FastAPI:
    app = FastAPI(title="Claude Docs Chatbot", docs_url=None, redoc_url=None)
    app.state.bot = bot or DocsBot(KnowledgeBase.from_folder(DOCS_DIR))
    app.state.limiter = limiter or RateLimiter(RATE_LIMIT)

    @app.post("/ask")
    def ask(body: AskRequest, request: Request):
        ip = request.client.host if request.client else "unknown"
        if not app.state.limiter.allow(ip):
            raise HTTPException(429, "Too many questions. Please wait a minute and try again.")
        if not body.question.strip():
            raise HTTPException(422, "Please type a question.")
        try:
            return app.state.bot.ask(body.question).to_dict()
        except RuntimeError as exc:  # missing API key
            log.error("%s", exc)
            raise HTTPException(503, "The assistant is not configured yet.")
        except anthropic.RateLimitError:
            log.warning("Anthropic rate limit reached")
            raise HTTPException(503, "The assistant is busy. Please try again in a minute.")
        except anthropic.APIStatusError as exc:
            log.error("Claude API error %s (request id %s)", exc.status_code, getattr(exc, "request_id", None))
            raise HTTPException(502, "The assistant is unavailable right now. Please try again later.")
        except anthropic.APIConnectionError:
            log.error("Could not reach the Claude API")
            raise HTTPException(502, "The assistant is unavailable right now. Please try again later.")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(BASE_DIR / "static" / "index.html")

    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    return app


app = create_app()
