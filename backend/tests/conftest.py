import json
import os
import sys
import tempfile

# Must be set before db.py is imported: tests use a throwaway database, never backend/local.db
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["PUBLIC_BASE_URL"] = "http://localhost:8000"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel

import db
from main import app


@pytest.fixture(autouse=True)
def fresh_database():
    SQLModel.metadata.drop_all(db.engine)
    db.init_db()
    yield


@pytest.fixture
def client():
    return TestClient(app)


class FakeChunk:
    def __init__(self, text, usage=None):
        self.text = text
        self.usage_metadata = usage


class FakeChatModel:
    """Stands in for a LangChain chat model: streams `text` a few characters at a time, reporting
    token usage the way providers do (input on the first chunk, output on the last), and records
    the prompts it was given. Set `fail` to an exception to make the call fail."""

    def __init__(self, text="Fake answer"):
        self.text = text
        self.prompts = []
        self.fail = None
        self.rewrites = []
        self.rewrite = "nursing program Peoria"
        self.fail_rewrite = None

    async def astream(self, prompt):
        self.prompts.append(prompt)
        if self.fail:
            raise self.fail
        pieces = [self.text[i:i + 3] for i in range(0, len(self.text), 3)]
        for i, piece in enumerate(pieces):
            yield FakeChunk(piece, {"input_tokens": 120, "output_tokens": 0} if i == 0 else None)
        yield FakeChunk("", {"input_tokens": 0, "output_tokens": 30})


    async def ainvoke(self, messages):
        """The query rewriter's call: records it and returns `rewrite` (default: the latest message unchanged)"""
        self.rewrites.append(messages)
        if self.fail_rewrite:
            raise self.fail_rewrite
        return FakeChunk(self.rewrite if self.rewrite is not None else "", {"input_tokens": 50, "output_tokens": 10})


class FakeJudge:
    """Stands in for the judge model behind with_structured_output; returns `verdict`"""

    def __init__(self):
        from evaluator import Verdict
        self.verdict = Verdict(groundedness=5, relevance=5, completeness=4, unsupported_claims=[], rationale="Fine.")
        self.calls = []
        self.fail = None

    def with_structured_output(self, schema, include_raw=False):
        return self

    async def ainvoke(self, messages):
        self.calls.append(messages)
        if self.fail:
            raise self.fail
        return {"raw": FakeChunk("", {"input_tokens": 900, "output_tokens": 60}), "parsed": self.verdict,
                "parsing_error": None}


@pytest.fixture
def fake_model(monkeypatch):
    """A configured provider whose chat model is a FakeChatModel (with a FakeJudge as `.judge`),
    and canned search results"""
    import answering
    import evaluator

    model = FakeChatModel()
    model.judge = FakeJudge()
    model.searches = []
    selection = {"provider": "anthropic", "model": "test-model", "api_key": "k"}
    results = [{"title": "Nursing (Section 1 of 2)", "content": "The nursing program is in Peoria.",
                "url": "https://www.bradley.edu/nursing", "score": 0.9, "content_type": "program",
                "chunk_index": 0, "total_chunks": 2}]

    async def fake_search(query, limit=5):
        model.searches.append(query)
        return results

    monkeypatch.setattr(answering, "get_chat_model", lambda: (model, selection))
    monkeypatch.setattr(evaluator, "get_judge_model", lambda: (model.judge, {**selection, "model": "judge-model"}))
    monkeypatch.setattr(answering.search_index, "search", fake_search)
    monkeypatch.setattr("routers.chat.active_selection", lambda: selection)
    monkeypatch.setattr("routers.system.active_selection", lambda: selection)
    return model


def ask(client, message, conversation_id=None):
    """POST /chat and read the stream: (the text pieces, the final "done" event)"""
    response = client.post("/chat", json={"message": message, "conversation_id": conversation_id})
    assert response.status_code == 200 and response.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert events[-1]["type"] == "done" and all(e["type"] == "delta" for e in events[:-1])
    return [e["text"] for e in events[:-1]], events[-1]
