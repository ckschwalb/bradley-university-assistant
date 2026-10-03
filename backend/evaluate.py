#!/usr/bin/env python3
"""
End-to-end answer quality: run a fixed question set through search, the chat model and the
quality judge, and report retrieval hit rate and the judge's scores.

Uses the indexed content, the active system prompt and the provider set up in the dashboard, so
it measures what users get. Each question costs two model calls (answer and judge). Nothing is
saved to the conversation history.

    python evaluate.py                                   # the embedding benchmark's 40 questions
    python evaluate.py --questions my.json --out results.json --limit 10

A questions file is a JSON list of [question, [paths of the pages that answer it]], the format of
eval/embedding-benchmark/questions.json.
"""

import argparse
import asyncio
import json
import os
import sys
from urllib.parse import urlsplit

from answering import generate
from db import init_db
from evaluator import GROUNDED, judge
from llm import judge_selection
from observability import mean

DEFAULT_QUESTIONS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "eval", "embedding-benchmark", "questions.json")


async def evaluate(question: str, targets: list) -> dict:
    answer = await generate(question, [])
    found = [urlsplit(r["url"]).path for r in answer.results]
    verdict, _, _ = await judge(question, [], answer)
    return {
        "question": question,
        "retrieval_hit": bool(set(found) & set(targets)),
        "answer": answer.text,
        "sources": [s["url"] for s in answer.sources],
        **verdict.model_dump(),
        "first_token_ms": answer.metrics["first_token_ms"],
        "total_ms": answer.metrics["total_ms"],
    }


def summarize(rows: list) -> dict:
    return {
        "questions": len(rows),
        "retrieval_hit_rate": round(sum(r["retrieval_hit"] for r in rows) / len(rows), 3),
        "groundedness": mean(r["groundedness"] for r in rows),
        "relevance": mean(r["relevance"] for r in rows),
        "completeness": mean(r["completeness"] for r in rows),
        "grounded_share": round(sum(r["groundedness"] >= GROUNDED for r in rows) / len(rows), 3),
        # The judge can only grade what search found: low completeness with a retrieval miss is a search problem
        "complete_when_retrieved": mean(r["completeness"] for r in rows if r["retrieval_hit"]),
    }


async def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--questions", default=DEFAULT_QUESTIONS, help="JSON list of [question, [page paths]]")
    parser.add_argument("--limit", type=int, help="Only the first N questions")
    parser.add_argument("--out", help="Also write every answer and verdict to this JSON file")
    args = parser.parse_args()

    init_db()
    selection = judge_selection()
    if selection is None:
        sys.exit("Set up an AI provider and turn on the quality judge in the dashboard (Assistant) first.")
    with open(args.questions, encoding="utf-8") as f:
        questions = json.load(f)[:args.limit]

    rows = []
    for i, (question, targets) in enumerate(questions, 1):
        row = await evaluate(question, targets)
        rows.append(row)
        print(f"{i:>3}/{len(questions)}  retrieved {'yes' if row['retrieval_hit'] else 'NO '}  "
              f"G{row['groundedness']} R{row['relevance']} C{row['completeness']}  {question[:70]}", flush=True)

    summary = summarize(rows)
    print("\n" + "\n".join(f"{k:>24}: {v}" for k, v in summary.items()))
    print(f"{'judge':>24}: {selection['provider']} / {selection['model']}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "judge": selection["model"], "rows": rows}, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    asyncio.run(main())
