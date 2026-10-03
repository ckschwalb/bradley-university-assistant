from conftest import ask
from sqlmodel import Session, select

import db
from models import AnswerEvaluation, Message, Trace


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_questions_are_limited_to_1000_characters(client, fake_model):
    from routers.chat import MAX_MESSAGE_CHARS
    assert MAX_MESSAGE_CHARS == 1000
    assert client.post("/chat", json={"message": "x" * 1001}).status_code == 422
    assert client.post("/chat", json={"message": ""}).status_code == 422
    _, done = ask(client, "x" * 1000)
    assert not done["error"]


def test_the_admin_api_is_open_until_a_token_is_set(client):
    assert client.get("/api/admin/overview").status_code == 200
    assert client.get("/api/status").json()["admin_token_required"] is False


def test_an_admin_token_protects_the_dashboard_but_not_the_chat(client, fake_model, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "s3cret")
    protected = [("get", "/api/admin/overview"), ("get", "/api/admin/conversations"),
                 ("get", "/api/admin/observability"), ("get", "/api/admin/system-prompt"),
                 ("get", "/api/settings/llm"), ("put", "/api/settings/llm"),
                 ("post", "/api/admin/clear-conversation-history")]
    for method, path in protected:
        assert getattr(client, method)(path).status_code == 401, path
    assert client.get("/api/admin/overview", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/admin/overview", headers={"Authorization": "s3cret"}).status_code == 401
    assert client.get("/api/admin/overview", headers={"Authorization": "Bearer s3cret"}).status_code == 200

    # What the chat widget uses stays public
    assert client.get("/health").status_code == 200
    assert client.get("/api/status").json()["admin_token_required"] is True
    assert client.get("/api/suggestions").status_code == 200
    ask(client, "Where is nursing?")


def test_without_a_key_the_chat_runs_in_demo_mode(client):
    assert client.get("/api/status").json()["demo_mode"] is True
    pieces, done = ask(client, "hi")
    assert done["demo"] is True and done["error"] is False
    assert "still being indexed" in done["response"] and "".join(pieces) == done["response"]
    assert done["conversation_id"] and done["assistant_message_id"]  # demo turns are saved like any other


def test_demo_mode_quotes_the_best_matching_pages_and_makes_no_provider_calls(client, monkeypatch):
    import answering
    results = [
        {"title": "Nursing (Section 2 of 3)", "url": "https://www.bradley.edu/nursing",
         "content": "# Nursing\n\nThe program has small classes.\n\nClinical rotations for nursing students start in the "
                    "second year at OSF Saint Francis Medical Center in Peoria.", "score": 0.8},
        {"title": "Nursing (Section 3 of 3)", "url": "https://www.bradley.edu/nursing", "content": "More.", "score": 0.7},
        {"title": "Health Sciences", "url": "https://www.bradley.edu/health", "content": "The College of Health "
         "Sciences offers nursing, physical therapy and more programs to students.", "score": 0.6},
    ]

    async def fake_search(query, limit=5):
        return results

    monkeypatch.setattr(answering.search_index, "search", fake_search)
    _, done = ask(client, "When do nursing clinical rotations start?")
    assert done["demo"] is True and done["model"] == "search-only"
    assert "> Clinical rotations for nursing students start in the second year" in done["response"]
    assert "**[Nursing](https://www.bradley.edu/nursing)**" in done["response"]
    assert [s["url"] for s in done["sources"]] == ["https://www.bradley.edu/nursing", "https://www.bradley.edu/health"]
    with Session(db.engine) as session:
        assert session.exec(select(Trace)).all() == [] and session.exec(select(AnswerEvaluation)).all() == []


def test_a_key_saved_from_the_start_screen_turns_demo_mode_off(client):
    client.put("/api/settings/llm", json={"provider": "anthropic", "api_key": "sk-ant-1234"})
    status = client.get("/api/status").json()
    assert status["demo_mode"] is False and status["provider_ready"] is True


def test_chat_saves_turn_and_returns_sources(client, fake_model):
    _, done = ask(client, "Where is nursing?")
    assert done["response"] == "Fake answer"
    assert done["sources"] == []  # the fake answer cites nothing, so nothing is listed as used
    with Session(db.engine) as session:
        roles = [m.role for m in session.exec(select(Message).where(Message.conversation_id == done["conversation_id"]))]
    assert sorted(roles) == ["assistant", "user"]
    assert "The nursing program is in Peoria." in str(fake_model.prompts[0])


def test_chat_streams_the_answer_as_it_is_written(client, fake_model):
    fake_model.text = "Nursing is in Peoria, in the College of Health Sciences.\n\nUsed: 1"
    pieces, done = ask(client, "Where is nursing?")
    assert len(pieces) > 1
    assert "".join(pieces).strip() == done["response"] == "Nursing is in Peoria, in the College of Health Sciences."
    assert not any("Used" in p or "Use" in p for p in pieces)  # the closing line never shows, even in part


def test_chat_sends_earlier_messages_as_history(client, fake_model):
    _, first = ask(client, "First question")
    ask(client, "Second", first["conversation_id"])
    assert "First question" in str(fake_model.prompts[1])


def test_failed_model_call_saves_nothing_and_is_traced(client, fake_model):
    fake_model.fail = RuntimeError("provider down")
    _, done = ask(client, "hi")
    assert done["error"] is True
    with Session(db.engine) as session:
        assert session.exec(select(Message)).all() == []
        trace = session.exec(select(Trace)).one()
    assert (trace.kind, trace.status, trace.error) == ("chat", "error", "RuntimeError: provider down")


def test_cross_site_writes_are_refused(client):
    refused = client.post("/api/admin/crawl/start", json={}, headers={"Origin": "https://evil.example"})
    assert refused.status_code == 403
    allowed = client.post("/api/admin/crawl/start", json={}, headers={"Origin": "http://localhost:8000"})
    assert allowed.status_code == 200


def test_feedback_validates_rating_and_message_ownership(client, fake_model):
    _, chat = ask(client, "hi")
    cid, mid = chat["conversation_id"], chat["assistant_message_id"]
    assert client.post("/api/feedback", json={"conversationId": cid, "rating": 5}).status_code == 400
    assert client.post("/api/feedback", json={"conversationId": "nope", "rating": 1}).status_code == 404
    assert client.post("/api/feedback", json={"conversationId": cid, "messageId": "nope", "rating": 1}).status_code == 404
    assert client.post("/api/feedback", json={"conversationId": cid, "messageId": mid, "rating": -1,
                                              "comment": "wrong"}).status_code == 200


def test_api_key_is_never_returned_by_settings(client):
    client.put("/api/settings/llm", json={"provider": "openai", "api_key": "sk-secret-1234"})
    body = client.get("/api/settings/llm").text
    assert "sk-secret" not in body and "1234" in body


def test_chat_lists_only_the_pages_the_answer_cites(client, fake_model):
    fake_model.text = "It's in Peoria.\n\nSources: [Nursing](https://www.bradley.edu/nursing/)"
    _, done = ask(client, "Where is nursing?")
    assert done["sources"] == [{"title": "Nursing", "url": "https://www.bradley.edu/nursing"}]


def test_used_line_is_hidden_and_its_pages_become_the_sources(client, fake_model):
    fake_model.text = "It's in Peoria. Nursing usually takes four years.\n\nUsed: 1"
    _, done = ask(client, "Where is nursing?")
    assert done["response"] == "It's in Peoria. Nursing usually takes four years."
    assert done["sources"] == [{"title": "Nursing", "url": "https://www.bradley.edu/nursing"}]
    saved = client.get(f"/api/admin/conversations/{done['conversation_id']}").json()["turns"][0]["answer"]
    assert "Used:" not in saved["text"]
    assert saved["cited"] == [{"label": "Nursing", "url": "https://www.bradley.edu/nursing"}]
    # it hedges ("usually") without links in the text, but it used a page, so it isn't flagged as unsupported
    assert saved["review"] == []


def test_answer_that_used_nothing_has_no_sources_and_is_flagged_when_it_hedges(client, fake_model):
    fake_model.text = "Nursing usually takes four years.\n\nUsed: none"
    _, done = ask(client, "How long is nursing?")
    assert done["sources"] == []
    saved = client.get(f"/api/admin/conversations/{done['conversation_id']}").json()["turns"][0]["answer"]
    assert [i["kind"] for i in saved["review"]] == ["unsupported"]


def test_conversations_cannot_be_shared_by_link(client, fake_model):
    _, done = ask(client, "hi")
    assert client.post(f"/api/admin/conversations/{done['conversation_id']}/share").status_code in (404, 405)
    assert client.get("/api/share/anything").status_code in (404, 405)


# ---- Quality judge ----------------------------------------------------------

def test_every_answer_is_judged_against_its_sources(client, fake_model):
    fake_model.text = "It's in Peoria.\n\nUsed: 1"
    _, done = ask(client, "Where is nursing?")
    prompt = str(fake_model.judge.calls[0])
    assert "Where is nursing?" in prompt and "The nursing program is in Peoria." in prompt
    assert "It's in Peoria." in prompt and "Sources the assistant says it used: 1" in prompt
    answer = client.get(f"/api/admin/conversations/{done['conversation_id']}").json()["turns"][0]["answer"]
    assert answer["evaluation"]["groundedness"] == 5 and answer["evaluation"]["model"] == "judge-model"
    assert answer["review"] == []


def test_a_poorly_grounded_answer_needs_review(client, fake_model):
    fake_model.judge.verdict = fake_model.judge.verdict.model_copy(update={
        "groundedness": 2, "unsupported_claims": ["Nursing takes four years"], "rationale": "Invents a duration."})
    _, done = ask(client, "How long is nursing?")
    review = client.get(f"/api/admin/conversations/{done['conversation_id']}").json()["turns"][0]["answer"]["review"]
    assert [i["kind"] for i in review] == ["ungrounded"]
    assert "Nursing takes four years" in review[0]["detail"]
    overview = client.get("/api/admin/overview").json()
    assert overview["review_total"] == 1 and overview["judged_this_week"] == 1 and overview["grounded_this_week"] == 0


def test_out_of_range_scores_are_clamped(client, fake_model):
    fake_model.judge.verdict = fake_model.judge.verdict.model_copy(update={"groundedness": 9, "relevance": 0})
    ask(client, "Where is nursing?")
    with Session(db.engine) as session:
        evaluation = session.exec(select(AnswerEvaluation)).one()
    assert (evaluation.groundedness, evaluation.relevance) == (5, 1)


def test_a_failed_judgement_is_traced_and_leaves_the_chat_alone(client, fake_model):
    fake_model.judge.fail = RuntimeError("judge down")
    _, done = ask(client, "Where is nursing?")
    assert done["error"] is False and done["assistant_message_id"]
    with Session(db.engine) as session:
        assert session.exec(select(AnswerEvaluation)).all() == []
        judge_trace = session.exec(select(Trace).where(Trace.kind == "judge")).one()
    assert judge_trace.status == "error" and judge_trace.message_id == done["assistant_message_id"]


def test_judge_settings_choose_a_model_or_turn_it_off(client):
    from llm import judge_selection
    client.put("/api/settings/llm", json={"provider": "anthropic", "api_key": "k", "model": "chat-model"})
    assert judge_selection()["model"] == "chat-model"  # the chat model by default
    view = client.put("/api/settings/judge", json={"enabled": True, "model": "bigger-model"}).json()
    assert view == {"enabled": True, "provider": "anthropic", "model": "bigger-model", "same_as_chat": False}
    assert judge_selection()["model"] == "bigger-model"
    client.put("/api/settings/judge", json={"enabled": False})
    assert judge_selection() is None


# ---- Observability ------------------------------------------------------------

def test_answers_and_judgements_are_traced_with_timings_and_tokens(client, fake_model):
    _, done = ask(client, "Where is nursing?")
    with Session(db.engine) as session:
        chat = session.exec(select(Trace).where(Trace.kind == "chat")).one()
        judge = session.exec(select(Trace).where(Trace.kind == "judge")).one()
    assert chat.status == "ok" and chat.message_id == done["assistant_message_id"]
    assert (chat.input_tokens, chat.output_tokens, chat.top_score) == (120, 30, 0.9)
    assert chat.search_ms is not None and chat.first_token_ms is not None and chat.total_ms >= chat.first_token_ms
    assert (judge.model, judge.input_tokens, judge.output_tokens) == ("judge-model", 900, 60)


def test_observability_summarizes_calls_and_quality(client, fake_model):
    ask(client, "Where is nursing?")
    fake_model.fail = RuntimeError("provider down")
    ask(client, "And pharmacy?")
    body = client.get("/api/admin/observability", params={"hours": 24, "tz": "America/Chicago"}).json()
    assert (body["chat"]["calls"], body["chat"]["errors"], body["chat"]["error_rate"]) == (2, 1, 0.5)
    assert body["chat"]["input_tokens"] == 120 and body["judge"]["calls"] == 1
    assert body["quality"]["judged"] == 1 and body["quality"]["groundedness"] == 5
    assert body["hourly"] is True and sum(p["answers"] for p in body["timeline"]) == 1
    assert body["models"][0]["model"] == "test-model" and body["models"][0]["groundedness"] == 5
    assert [t["kind"] for t in body["recent"]] == ["chat", "judge", "chat"]
    week = client.get("/api/admin/observability", params={"hours": 24 * 7, "tz": "Nowhere/Invalid"}).json()
    assert week["hourly"] is False and len(week["timeline"]) in (7, 8)  # whole days, in UTC for an unknown zone


def test_deleting_a_conversation_removes_its_evaluations_but_keeps_traces(client, fake_model):
    _, done = ask(client, "Where is nursing?")
    client.delete(f"/api/admin/conversations/{done['conversation_id']}")
    with Session(db.engine) as session:
        assert session.exec(select(AnswerEvaluation)).all() == []
        assert len(session.exec(select(Trace)).all()) == 2
    recent = client.get("/api/admin/observability").json()["recent"]
    assert all(t["conversation_id"] is None for t in recent)  # no link to a conversation that's gone


def test_offline_evaluation_scores_retrieval_and_answers(fake_model):
    import asyncio

    import evaluate

    fake_model.text = "In Peoria.\n\nUsed: 1"
    hit = asyncio.run(evaluate.evaluate("Where is nursing?", ["/nursing"]))
    miss = asyncio.run(evaluate.evaluate("Where is pharmacy?", ["/pharmacy/"]))
    assert (hit["retrieval_hit"], miss["retrieval_hit"]) == (True, False)
    assert hit["answer"] == "In Peoria." and hit["groundedness"] == 5
    summary = evaluate.summarize([hit, miss])
    assert summary["retrieval_hit_rate"] == 0.5 and summary["grounded_share"] == 1.0


def test_the_system_prompt_is_one_saved_text_that_can_go_back_to_the_default(client, fake_model):
    import system_prompt
    default = client.get("/api/admin/system-prompt").json()
    assert default["is_default"] is True and default["content"] == default["default_content"]
    client.post("/api/admin/system-prompt", json={"content": "First edit {context}"})
    saved = client.post("/api/admin/system-prompt", json={"content": "Second edit {context}"}).json()
    assert saved["is_default"] is False and saved["content"] == "Second edit {context}" and saved["saved_at"]
    assert system_prompt.active_prompt() == "Second edit {context}"
    ask(client, "Where is nursing?")
    assert "Second edit" in str(fake_model.prompts[0])
    with Session(db.engine) as session:
        from models import SavedPrompt
        assert len(session.exec(select(SavedPrompt)).all()) == 1  # replaced, not kept as versions
    back = client.post("/api/admin/system-prompt", json={"content": default["default_content"]}).json()
    assert back["is_default"] is True
    assert client.get("/api/admin/system-prompt/history").status_code == 404  # no version history any more
    assert client.post("/api/admin/system-prompt", json={"content": "  "}).status_code == 400


def test_follow_up_questions_are_searched_as_standalone_queries(client, fake_model):
    _, first = ask(client, "Tell me about nursing")
    assert fake_model.rewrites == [] and fake_model.searches == ["Tell me about nursing"]  # nothing to resolve yet

    ask(client, "what about their email?", first["conversation_id"])
    assert fake_model.searches[-1] == "nursing program Peoria"
    assert "Tell me about nursing" in str(fake_model.rewrites[0])
    # The answer is still written from the question as the user asked it
    assert "what about their email?" in str(fake_model.prompts[-1])
    saved = client.get(f"/api/admin/conversations/{first['conversation_id']}").json()
    assert "nursing program Peoria" in str(saved)


def test_a_failed_or_empty_rewrite_falls_back_to_the_question(client, fake_model):
    _, first = ask(client, "Tell me about nursing")
    fake_model.fail_rewrite = RuntimeError("boom")
    _, done = ask(client, "and the cost?", first["conversation_id"])
    assert not done["error"] and fake_model.searches[-1] == "and the cost?"

    fake_model.fail_rewrite, fake_model.rewrite = None, "   "
    ask(client, "and the deadline?", first["conversation_id"])
    assert fake_model.searches[-1] == "and the deadline?"


def test_a_listed_unsupported_claim_caps_groundedness_and_needs_review(client, fake_model):
    fake_model.judge.verdict = fake_model.judge.verdict.model_copy(
        update={"groundedness": 4, "unsupported_claims": ["MIS 375 is taught by her"]})
    _, done = ask(client, "Where is nursing?")
    with Session(db.engine) as session:
        evaluation = session.exec(select(AnswerEvaluation)).one()
    assert evaluation.groundedness == 3
    detail = client.get(f"/api/admin/conversations/{done['conversation_id']}").json()
    assert detail["tags"], "an answer with an unsupported claim is on the Needs review list"


def test_the_rewriter_sees_shortened_history_and_a_capped_query(client, fake_model):
    long_answer = "Angelica Perdue teaches MIS 173. " * 40
    fake_model.text = long_answer
    _, first = ask(client, "who is angelica perdue")
    fake_model.rewrite = "Angelica Perdue courses taught " + "x" * 500
    ask(client, "what does she teach?", first["conversation_id"])
    shown = fake_model.rewrites[0][1].content
    assert len(shown) < len(long_answer) and "…" in shown
    assert len(fake_model.searches[-1]) <= 200


def test_model_list_leaves_out_models_that_no_longer_work(monkeypatch):
    import llm
    monkeypatch.setattr(llm, "list_models", lambda provider, key: ["good", "retired", "flaky"])
    outcomes = {"good": True, "retired": False, "flaky": True}
    monkeypatch.setattr(llm, "_probe", lambda provider, model, key: outcomes[model])
    llm._probe_cache.clear()
    assert llm.available_models("openai", "key") == ["good", "flaky"]


def test_a_probe_drops_models_the_provider_rejects_but_not_ones_it_cannot_judge(monkeypatch):
    import llm

    def model_failing_with(status):
        class Rejected(Exception):
            status_code = status

        class Model:
            def invoke(self, prompt):
                if status:
                    raise Rejected("no")
        return Model()

    for status, works in [(None, True), (404, False), (400, False), (401, True), (429, True), (500, True)]:
        monkeypatch.setattr(llm, "init_chat_model", lambda *a, _s=status, **k: model_failing_with(_s))
        assert llm._probe("openai", "m", "key") is works, status


def test_the_models_endpoint_serves_only_working_models(client, monkeypatch):
    import llm
    monkeypatch.setattr(llm, "list_models", lambda provider, key: ["gpt-new", "gpt-5-chat-latest"])
    monkeypatch.setattr(llm, "_probe", lambda provider, model, key: model == "gpt-new")
    llm._probe_cache.clear()
    body = client.post("/api/settings/llm/models", json={"provider": "openai", "api_key": "k"}).json()
    assert body["models"] == ["gpt-new"]
