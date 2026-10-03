import React, { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import { useAdmin } from './AdminApp';
import { api, formatTime, formatWhen, plural } from './api';
import { useApi } from './useApi';

const FILTERS = [
  ['all', 'All'],
  ['review', 'Needs review'],
  ['rated', 'Rated'],
];

const EMPTY_TEXT = {
  all: 'No conversations yet. They appear here as soon as someone asks the assistant a question.',
  review: 'Nothing needs review.',
  rated: 'No answers have been rated yet.',
};

const TAG_TONE = { no_answer: 'warn', formatting: 'plain', weak_answer: 'warn' };
const SEARCH_KINDS = ['no_answer', 'unknown_link', 'unsupported', 'ungrounded', 'weak_answer'];

const markdownLinks = { a: ({ node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer">{props.children}</a> };

const ReviewNote = ({ item, onResolve }) => (
  <div className="callout warn">
    <span><strong>{item.label}:</strong> {item.detail}</span>
    <span className="row" style={{ flexShrink: 0 }}>
      {item.question && SEARCH_KINDS.includes(item.kind) && (
        <Link className="btn sm" to={`/admin/knowledge?test=${encodeURIComponent(item.question)}`}>Test search</Link>
      )}
      <button type="button" className="btn sm" onClick={() => onResolve(item)}>Mark reviewed</button>
    </span>
  </div>
);

const score = (value) => <span className={`chip ${value >= 4 ? 'good' : value === 3 ? 'warn' : 'bad'}`}>{value}/5</span>;

// The quality judge's scores for one answer, with its reasoning a click away
const Evaluation = ({ evaluation }) => (
  <details className="evaluation">
    <summary>
      Judge: grounded {score(evaluation.groundedness)} relevant {score(evaluation.relevance)} complete {score(evaluation.completeness)}
    </summary>
    <p>{evaluation.rationale}</p>
    {evaluation.unsupported_claims.length > 0 && (
      <ul>{evaluation.unsupported_claims.map((claim, i) => <li key={i}>Not in the sources: “{claim}”</li>)}</ul>
    )}
    <p className="mono">{evaluation.model}</p>
  </details>
);

const Answer = ({ answer, onResolve }) => (
  <div id={`m-${answer.id}`} className={`bubble-a${answer.review.length ? ' has-issue' : ''}`}>
    <div className="answer-text">
      <ReactMarkdown components={markdownLinks}>{answer.text}</ReactMarkdown>
    </div>
    {answer.review.length > 0 && (
      <div className="answer-review">
        {answer.review.map((item) => <ReviewNote key={item.key} item={item} onResolve={onResolve} />)}
      </div>
    )}
    <div className="answer-meta">
      <span>{formatTime(answer.at)}{answer.model && <> · <span className="mono">{answer.model}</span></>}</span>
      {answer.cited.length > 0
        ? answer.cited.map((link) => (
            <a key={link.url} href={link.url} target="_blank" rel="noopener noreferrer">{link.label}</a>
          ))
        : <span className="chip plain">No sources cited</span>}
      {answer.feedback.map((fb, i) => (
        <span key={i} className={`chip ${fb.rating === 1 ? 'good' : 'bad'}`} title={fb.comment || undefined}>
          {fb.rating === 1 ? 'Rated helpful' : 'Rated not helpful'}
        </span>
      ))}
    </div>
    {answer.feedback.filter((fb) => fb.comment).map((fb, i) => (
      <div key={i} className="callout plain">User comment: “{fb.comment}”</div>
    ))}
    {answer.evaluation && <Evaluation evaluation={answer.evaluation} />}
    {answer.retrieved && answer.retrieved.length > 0 && (
      <details className="retrieved">
        <summary>What search returned ({answer.retrieved.length})</summary>
        {answer.search_query && <p>Searched for: <em>{answer.search_query}</em></p>}
        <ol>
          {answer.retrieved.map((r, i) => (
            <li key={i}>
              <a href={r.url} target="_blank" rel="noopener noreferrer">{r.title}</a>{' '}
              <span className="mono">{r.score.toFixed(3)}</span>
            </li>
          ))}
        </ol>
      </details>
    )}
  </div>
);

const Conversations = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const { refreshCounts, notify } = useAdmin();

  const filter = params.get('filter') || 'all';
  const [query, setQuery] = useState(params.get('q') || '');
  const [failure, setFailure] = useState({ id: null, message: '' }); // from an action on one conversation
  const actionError = failure.id === id ? failure.message : '';
  const setError = (message) => setFailure({ id, message });
  const [busy, setBusy] = useState(false);

  const search = new URLSearchParams({ filter });
  if (params.get('q')) search.set('q', params.get('q'));
  const { data: list, reload: loadList, error: listError } = useApi(`/api/admin/conversations?${search}`, { keepPrevious: true });
  const { data: detail, reload: loadDetail, error: detailError } = useApi(id && `/api/admin/conversations/${id}`);
  const error = actionError || detailError || listError;

  useEffect(() => {
    document.title = 'Conversations · Bradley Assistant admin';
  }, []);

  // Typing in the search box updates ?q= after a short pause
  useEffect(() => {
    const timer = setTimeout(() => {
      if ((params.get('q') || '') === query.trim()) return;
      const next = new URLSearchParams(params);
      if (query.trim()) next.set('q', query.trim()); else next.delete('q');
      setParams(next, { replace: true });
    }, 300);
    return () => clearTimeout(timer);
  }, [query, params, setParams]);

  // With nothing selected, open the newest conversation in the list
  useEffect(() => {
    if (!id && list && list.conversations.length > 0) {
      navigate(`/admin/conversations/${list.conversations[0].id}${location.search}`, { replace: true });
    }
  }, [id, list, navigate, location.search]);

  // Links from Needs review point at one answer (#m-<id>)
  useEffect(() => {
    if (detail && location.hash) {
      const el = document.getElementById(location.hash.slice(1));
      if (el) el.scrollIntoView({ block: 'center' });
    }
  }, [detail, location.hash]);

  const setFilter = (value) => {
    const next = new URLSearchParams(params);
    if (value === 'all') next.delete('filter'); else next.set('filter', value);
    navigate(`/admin/conversations?${next}`);
  };

  const resolve = async (item) => {
    try {
      await api('/api/admin/review/resolve', { method: 'POST', body: { key: item.key } });
      await Promise.all([loadDetail(), loadList()]);
      refreshCounts();
      notify('Marked as reviewed.');
    } catch (e) {
      setError(e.message);
    }
  };

  const remove = async () => {
    if (!window.confirm('Delete this conversation, and its ratings? This cannot be undone.')) return;
    setBusy(true);
    try {
      await api(`/api/admin/conversations/${id}`, { method: 'DELETE' });
      notify('Conversation deleted.');
      refreshCounts();
      await loadList();
      navigate(`/admin/conversations${location.search}`, { replace: true });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const clearAll = async () => {
    if (!window.confirm('Delete ALL conversations, messages, and ratings? This cannot be undone.')) return;
    try {
      await api('/api/admin/clear-conversation-history', { method: 'POST' });
      notify('All conversations deleted.');
      refreshCounts();
      await loadList();
      navigate('/admin/conversations', { replace: true });
    } catch (e) {
      setError(e.message);
    }
  };

  const counts = list ? list.counts : {};

  return (
    <div className="convo-layout">
      <section className="convo-list" aria-label="Conversation list">
        <div className="convo-list-head">
          <h1 style={{ fontSize: 22, fontWeight: 700 }}>Conversations</h1>
          <label className="field" style={{ fontSize: 12, color: 'var(--muted)' }}>
            Search questions and answers
            <input
              className="input"
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g. deadline, CS 210, president"
            />
          </label>
          <div className="row" role="group" aria-label="Filter" style={{ gap: 6 }}>
            {FILTERS.map(([value, label]) => (
              <button
                key={value}
                type="button"
                className="pill"
                aria-pressed={filter === value}
                onClick={() => setFilter(value)}
              >
                {label} {counts[value] !== undefined && counts[value]}
              </button>
            ))}
          </div>
        </div>
        <div className="convo-list-items">
          {list && list.conversations.map((c) => (
            <Link
              key={c.id}
              to={`/admin/conversations/${c.id}${location.search}`}
              className={`convo-row${c.id === id ? ' active' : ''}`}
              aria-current={c.id === id ? 'page' : undefined}
            >
              <span className="row tiny muted" style={{ justifyContent: 'space-between' }}>
                <span>{formatWhen(c.last_at)}</span>
                <span>{plural(c.questions, 'question')}</span>
              </span>
              <span className="convo-row-title">{c.title}</span>
              {c.tags.length > 0 && (
                <span className="row" style={{ gap: 4 }}>
                  {c.tags.map((t) => <span key={t.kind} className={`chip ${TAG_TONE[t.kind] || 'bad'}`}>{t.label}</span>)}
                </span>
              )}
            </Link>
          ))}
          {list && list.conversations.length === 0 && (
            <p className="empty">{params.get('q') ? `Nothing matches “${params.get('q')}”.` : EMPTY_TEXT[filter]}</p>
          )}
        </div>
        {counts.all > 0 && (
          <div className="convo-list-foot">
            <button type="button" className="link-btn" style={{ paddingLeft: 0 }} onClick={clearAll}>
              Delete all conversations…
            </button>
          </div>
        )}
      </section>

      <section className="transcript" aria-label="Transcript">
        {error && <div className="callout bad" role="alert" style={{ margin: '16px 32px 0' }}>{error}</div>}
        {detail && (
          <>
            <header className="transcript-head">
              <div style={{ minWidth: 0 }}>
                <h2>{detail.title}</h2>
                <p className="muted small" style={{ marginTop: 4 }}>
                  {formatWhen(detail.started_at)} · {plural(detail.questions, 'question')}
                  {detail.models.length > 0 && ` · answered by ${detail.models.join(', ')}`}
                </p>
              </div>
              <div className="row">
                <button type="button" className="btn sm danger" onClick={remove} disabled={busy}>Delete</button>
              </div>
            </header>
            <div className="transcript-body">
              {detail.turns.map((turn, i) => (
                <div key={i} className="turn">
                  {turn.question && <div className="bubble-q">{turn.question.text}</div>}
                  {turn.answer && <Answer answer={turn.answer} onResolve={resolve} />}
                </div>
              ))}
            </div>
          </>
        )}
        {!detail && !error && list && list.conversations.length === 0 && (
          <p className="empty" style={{ marginTop: 80 }}>Select a conversation to read it.</p>
        )}
      </section>
    </div>
  );
};

export default Conversations;
