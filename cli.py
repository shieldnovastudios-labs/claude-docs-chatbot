"""Ask the chatbot from the terminal.

    python cli.py "What time do you open on Saturday?"
    python cli.py            # interactive mode, empty line or Ctrl+C to quit
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bot import DocsBot
from kb import KnowledgeBase

MAX_QUESTION_CHARS = 500


def show(bot: DocsBot, question: str) -> None:
    if len(question) > MAX_QUESTION_CHARS:
        print(f"Please keep questions under {MAX_QUESTION_CHARS} characters.")
        return
    answer = bot.ask(question)
    print(f"\n{answer.text}")
    for src in answer.sources:
        label = f"{src.document} — {src.section}" if src.section else src.document
        print(f"  source: {label}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask questions answered only from your documents.")
    parser.add_argument("question", nargs="*", help="question to ask (omit for interactive mode)")
    parser.add_argument("--docs", default=str(Path(__file__).resolve().parent / "docs"), help="docs folder")
    parser.add_argument("--search-only", action="store_true", help="show matching chunks, no API call")
    args = parser.parse_args()

    kb = KnowledgeBase.from_folder(Path(args.docs))
    bot = DocsBot(kb)

    if args.search_only:
        for score, chunk in kb.search(" ".join(args.question)):
            print(f"{score:5.2f}  {chunk.title}")
        return 0

    try:
        if args.question:
            show(bot, " ".join(args.question))
            return 0
        print(f"Loaded {len(kb.chunks)} chunks from {args.docs}. Ask a question (empty line to quit).")
        while True:
            question = input("> ").strip()
            if not question:
                return 0
            show(bot, question)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
