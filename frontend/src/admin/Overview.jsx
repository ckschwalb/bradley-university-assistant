import React from 'react';
import { Link } from 'react-router-dom';
import { Page, useAdmin } from './AdminApp';
import { api, formatDay, formatTime, formatWhen, isSameDay, plural } from './api';
import { formatDate } from '../lib/time';
import { crawlState, indexedItems, nextCrawlAt } from './crawl';
import { useApi } from './useApi';

const TONE = { no_answer: 'warn', unknown_link: 'bad', unsupported: 'bad', formatting: 'plain', ungrounded: 'bad', weak_answer: 'warn', rated_down: 'bad' };

// The second button on a review item: where to go to fix this kind of problem
const fixFor = (item) => {
  const test = item.question && `/admin/knowledge?test=${encodeURIComponent(item.question)}`;
  switch (item.kind) {
    case 'no_answer':
    case 'unknown_link':
    case 'unsupported':
    case 'ungrounded':
    case 'weak_answer':
      return test && { to: test, label: 'Test this search' };
    case 'formatting':
      return { to: '/admin/assistant', label: 'Edit instructions' };
    default:
      return null;
  }
};

export const conversationLink = (item) =>
  `/admin/conversations/${item.conversation_id}${item.message_id ? `#m-${item.message_id}` : ''}`;

const Overview = () => {
  const { llm, active, crawl, refreshCounts, notify } = useAdmin();
  const { data, setData, error, setError } = useApi('/api/admin/overview');

  const resolve = async (item) => {
    try {
      await api('/api/admin/review/resolve', { method: 'POST', body: { key: item.key } });
      setData((d) => ({ ...d, review: d.review.filter((i) => i.key !== item.key), review_total: d.review_total - 1 }));
      refreshCounts();
      notify('Marked as reviewed.');
    } catch (e) {
      setError(e.message);
    }
  };

  const state = crawlState(crawl);
  const next = nextCrawlAt(crawl);
  const today = formatDate(new Date(), { weekday: 'long', month: 'long', day: 'numeric' });

  return (
    <Page
      title="Overview"
      subtitle={today}
    >
      {error && <div className="callout bad" role="alert">{error}</div>}

      {llm && !active && (
        <div className="callout warn row" style={{ justifyContent: 'space-between' }}>
          <span><strong>The chat is in demo mode:</strong> it answers by quoting Bradley's website. Add an API key for Claude, OpenAI or Gemini for AI-written answers.</span>
          <Link className="btn sm primary" to="/admin/assistant">Add an API key</Link>
        </div>
      )}

      <section aria-label="System health" className="health-grid">
        <div className="card health-card">
          <div className="health-card-top">
            <span className="label">Answers</span>
            {llm && (active ? <span className="chip good">● Working</span> : <span className="chip warn">● Demo mode</span>)}
          </div>
          <div className="health-card-value">
            {active ? <>{active.label.split(' ')[0]} · <span className="mono">{active.model}</span></> : 'Quoting the website'}
          </div>
          <div className="muted small">
            {active ? `Key ${active.key_hint} saved` : 'Add an API key for AI-written answers'}
          </div>
          <Link to="/admin/assistant">Change provider or instructions</Link>
        </div>

        <div className="card health-card">
          <div className="health-card-top">
            <span className="label">Knowledge</span>
            <span className={`chip ${state.tone}`}>● {state.label}</span>
          </div>
          <div className="health-card-value">{crawl ? plural(indexedItems(crawl), 'page and course', 'pages and courses') : '—'}</div>
          <div className="muted small">
            {crawl && crawl.finished_at ? `Last crawl ${formatWhen(crawl.finished_at)}` : 'Not crawled yet'}
            {next && ` · next ${formatWhen(next)}`}
          </div>
          <Link to="/admin/knowledge">See what's indexed</Link>
        </div>

        <div className="card health-card">
          <div className="health-card-top">
            <span className="label">Crawler</span>
            {crawl && (crawl.crawler_online
              ? <span className={`chip ${crawl.status === 'running' ? 'good' : 'plain'}`}>● {crawl.status === 'running' ? 'Running' : 'Idle'}</span>
              : <span className="chip bad">● Offline</span>)}
          </div>
          <div className="health-card-value">{crawl ? (crawl.crawler_online ? 'Online' : 'Not running') : '—'}</div>
          <div className="muted small">
            {crawl && (crawl.auto_crawl.enabled ? `Auto-crawl every ${plural(crawl.auto_crawl.interval_hours, 'hour')}` : 'Auto-crawl is off')}
          </div>
          <Link to="/admin/knowledge">Crawl now</Link>
        </div>
      </section>

      {data && (
        <>
          <section aria-label="Usage" className="stat-grid">
            <div className="card card-pad">
              <div className="label">Conversations</div>
              <div className="stat-value">{data.conversations.toLocaleString('en-US')}</div>
              <div className="muted small">
                {data.first_conversation_at ? `${data.conversations_this_week} in the last 7 days` : 'none yet'}
              </div>
            </div>
            <div className="card card-pad">
              <div className="label">Questions asked</div>
              <div className="stat-value">{data.questions.toLocaleString('en-US')}</div>
              <div className="muted small">{plural(data.follow_up_conversations, 'conversation')} with follow-ups</div>
            </div>
            <div className="card card-pad">
              <div className="label">Answer ratings</div>
              <div className="stat-value">{(data.ratings_up + data.ratings_down).toLocaleString('en-US')}</div>
              <div className="muted small">
                {data.ratings_up + data.ratings_down === 0
                  ? 'no thumbs up or down yet'
                  : `${data.ratings_up} helpful · ${data.ratings_down} not helpful`}
              </div>
            </div>
            <div className="card card-pad">
              <div className="label">Grounded answers</div>
              <div className="stat-value">
                {data.judged_this_week ? `${Math.round((100 * data.grounded_this_week) / data.judged_this_week)}%` : '—'}
              </div>
              <div className="muted small">
                {data.judged_this_week
                  ? <>of {plural(data.judged_this_week, 'judged answer')} this week · <Link to="/admin/observability">details</Link></>
                  : 'no answers judged this week'}
              </div>
            </div>
          </section>

          <div className="overview-split">
            <section className="card" aria-labelledby="review-h">
              <div className="card-head">
                <div>
                  <h2 id="review-h">Needs review</h2>
                  <p>Answers that look wrong or that the quality judge scored low, plus anything users rate down</p>
                </div>
                {data.review_total > 0 && <span className="chip bad">{data.review_total} open</span>}
              </div>
              {data.review.map((item) => {
                const fix = fixFor(item);
                return (
                  <article key={item.key} className="review-item">
                    <div className="row">
                      <span className={`chip ${TONE[item.kind] || 'plain'}`}>{item.label}</span>
                      <span className="tiny muted">{formatWhen(item.at)}</span>
                    </div>
                    {item.question && <div className="review-question">“{item.question}”</div>}
                    <p style={{ color: 'var(--ink-2)' }}>{item.detail}</p>
                    <div className="row" style={{ marginTop: 4 }}>
                      <Link className="btn sm" to={conversationLink(item)}>Read conversation</Link>
                      {fix && <Link className="btn sm" to={fix.to}>{fix.label}</Link>}
                      <button type="button" className="btn sm ghost" onClick={() => resolve(item)}>Mark reviewed</button>
                    </div>
                  </article>
                );
              })}
              {data.review.length === 0 && (
                <div className="empty" style={{ borderTop: '1px solid var(--border-soft)' }}>
                  Nothing to review. Answers that look wrong, low judge scores and thumbs-down ratings show up here.
                </div>
              )}
              {data.review_total > data.review.length && (
                <div className="card-pad small" style={{ borderTop: '1px solid var(--border-soft)' }}>
                  <Link to="/admin/conversations?filter=review">See all {data.review_total} in Conversations</Link>
                </div>
              )}
            </section>

            <section className="card" aria-labelledby="recent-h">
              <div className="card-head">
                <h2 id="recent-h">Recent questions</h2>
                <Link className="small" to="/admin/conversations" style={{ fontWeight: 600 }}>All conversations</Link>
              </div>
              {data.recent_questions.length > 0 ? (
                <ol className="recent-list">
                  {data.recent_questions.map((q, i) => (
                    <li key={i}>
                      <Link to={`/admin/conversations/${q.conversation_id}`}>
                        <span style={{ minWidth: 0 }}>{q.text}</span>
                        <span className="tiny muted nowrap">
                          {isSameDay(q.at, new Date()) ? formatTime(q.at) : formatDay(q.at)}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ol>
              ) : (
                <div className="empty">No questions yet.</div>
              )}
            </section>
          </div>
        </>
      )}
    </Page>
  );
};

export default Overview;
