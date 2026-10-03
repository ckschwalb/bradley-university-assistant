import React, { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Page } from './AdminApp';
import { formatTime, formatWhen, plural } from './api';
import { useApi } from './useApi';
import { formatDate, viewerTimeZone } from '../lib/time';

const RANGES = [
  ['24h', 'Last 24 hours', 24],
  ['7d', 'Last 7 days', 24 * 7],
  ['30d', 'Last 30 days', 24 * 30],
];
const KIND_LABELS = { chat: 'Chat answer', judge: 'Quality judge', preview: 'Prompt preview' };

const compact = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 });
const formatMs = (ms) => (ms == null ? '—' : ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`);
const formatTokens = (n) => (n == null ? '—' : compact.format(n < 1000 ? Math.round(n) : n));
const formatShare = (share) => (share == null ? '—' : `${Math.round(share * 100)}%`);
const formatScore = (score) => (score == null ? '—' : score.toFixed(1));

// Round, evenly spaced y-axis ticks from 0 up to at least `max`
const niceTicks = (max, count = 4) => {
  const raw = Math.max(1, max) / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = Math.max(1, [1, 2, 5, 10].map((m) => m * magnitude).find((s) => s >= raw));
  const ticks = [];
  for (let t = 0; ticks.length === 0 || ticks[ticks.length - 1] < max; t += step) ticks.push(t);
  return ticks.length > 1 ? ticks : [0, step];
};

const Stat = ({ label, value, children }) => (
  <div className="card card-pad">
    <div className="label">{label}</div>
    <div className="stat-value">{value}</div>
    <div className="muted small">{children}</div>
  </div>
);

// Answers and failed requests per hour or day, as stacked columns with a tooltip per column
const ActivityChart = ({ points, hourly }) => {
  const [hover, setHover] = useState(null);
  const ticks = niceTicks(Math.max(...points.map((p) => p.answers + p.errors)));
  const top = ticks[ticks.length - 1];
  const bucketLabel = (p) => (hourly
    ? `${formatDate(p.start, { month: 'short', day: 'numeric' })}, ${formatTime(p.start)}`
    : formatDate(p.start, { weekday: 'short', month: 'short', day: 'numeric' }));
  const axisLabel = (p) => (hourly ? formatTime(p.start) : formatDate(p.start, { month: 'short', day: 'numeric' }));
  const labelEvery = Math.ceil(points.length / 8);
  const shown = hover !== null ? points[hover] : null;

  return (
    <div className="chart">
      <div className="chart-legend" aria-hidden="true">
        <span><i className="swatch answers" /> Answers</span>
        <span><i className="swatch errors" /> Failed requests</span>
      </div>
      <div className="chart-body">
        <div className="chart-plot" onMouseLeave={() => setHover(null)}>
          {ticks.map((t) => (
            <div key={t} className="chart-grid" style={{ bottom: `${(t / top) * 100}%` }}>
              <span>{t.toLocaleString('en-US')}</span>
            </div>
          ))}
          <div className="chart-columns">
            {points.map((p, i) => {
              const total = p.answers + p.errors;
              return (
                <div
                  key={p.start}
                  className={`chart-slot${hover === i ? ' hover' : ''}`}
                  tabIndex={0}
                  aria-label={`${bucketLabel(p)}: ${plural(p.answers, 'answer')}, ${plural(p.errors, 'failed request')}`}
                  onMouseEnter={() => setHover(i)}
                  onFocus={() => setHover(i)}
                  onBlur={() => setHover(null)}
                >
                  {total > 0 && (
                    <div className="chart-stack" style={{ height: `${(total / top) * 100}%` }}>
                      {p.errors > 0 && <div className="segment errors" style={{ flexGrow: p.errors }} />}
                      {p.answers > 0 && <div className="segment answers" style={{ flexGrow: p.answers }} />}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          {shown && (
            <div className="chart-tooltip" role="status"
              style={{ left: `${((hover + 0.5) / points.length) * 100}%` }}>
              <strong>{bucketLabel(shown)}</strong>
              <span><i className="swatch answers" /> {plural(shown.answers, 'answer')}</span>
              <span><i className="swatch errors" /> {plural(shown.errors, 'failed request')}</span>
              {shown.p95_ms != null && <span>p95 response {formatMs(shown.p95_ms)}</span>}
              {shown.groundedness != null && <span>Groundedness {formatScore(shown.groundedness)}/5</span>}
            </div>
          )}
        </div>
        <div className="chart-axis">
          {points.map((p, i) => <span key={p.start}>{i % labelEvery === 0 ? axisLabel(p) : ''}</span>)}
        </div>
      </div>
      <details className="chart-table">
        <summary>Show as a table</summary>
        <table>
          <thead><tr><th>{hourly ? 'Hour' : 'Day'}</th><th>Answers</th><th>Failed</th><th>p95 response</th><th>Groundedness</th></tr></thead>
          <tbody>
            {points.map((p) => (
              <tr key={p.start}>
                <td>{bucketLabel(p)}</td><td>{p.answers}</td><td>{p.errors}</td><td>{formatMs(p.p95_ms)}</td>
                <td>{formatScore(p.groundedness)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
};

const Observability = () => {
  const [params, setParams] = useSearchParams();
  const range = RANGES.find(([id]) => id === params.get('range')) || RANGES[1];
  const query = new URLSearchParams({ hours: range[2], tz: viewerTimeZone() });
  const { data, error } = useApi(`/api/admin/observability?${query}`, { keepPrevious: true });

  const chat = data && data.chat;
  const quality = data && data.quality;

  return (
    <Page
      title="Observability"
      subtitle="How the AI calls behind the chat are performing, and how good the answers are"
      actions={
        <div className="row" role="group" aria-label="Time range" style={{ gap: 6 }}>
          {RANGES.map(([id, label]) => (
            <button key={id} type="button" className="pill" aria-pressed={range[0] === id}
              onClick={() => setParams(id === '7d' ? {} : { range: id }, { replace: true })}>
              {label}
            </button>
          ))}
        </div>
      }
    >
      {error && <div className="callout bad" role="alert">{error}</div>}

      {data && (
        <>
          <section aria-label="Summary" className="stat-grid">
            <Stat label="Chat answers" value={(chat.calls - chat.errors).toLocaleString('en-US')}>
              {chat.calls === 0 ? 'no questions in this period'
                : chat.errors ? `${plural(chat.errors, 'failed request')} (${formatShare(chat.error_rate)})` : 'no failed requests'}
            </Stat>
            <Stat label="Response time" value={formatMs(chat.p50_ms)}>
              median · p95 {formatMs(chat.p95_ms)} · first words after {formatMs(chat.p50_first_token_ms)}
            </Stat>
            <Stat label="Tokens" value={formatTokens(chat.input_tokens + chat.output_tokens)}>
              {chat.avg_input_tokens != null
                ? `${formatTokens(chat.avg_input_tokens)} in · ${formatTokens(chat.avg_output_tokens)} out per answer`
                : 'none used'}
              {data.judge.calls > 0 && ` · judge ${formatTokens(data.judge.input_tokens + data.judge.output_tokens)}`}
            </Stat>
            <Stat label="Grounded answers" value={formatShare(quality.grounded_share)}>
              {quality.judged
                ? `scored ${quality.threshold}+ of 5 by the judge, of ${plural(quality.judged, 'answer')}`
                : <>no answers judged · <Link to="/admin/assistant">set up the judge</Link></>}
            </Stat>
          </section>

          <div className="overview-split">
            <section className="card" aria-labelledby="activity-h">
              <div className="card-head">
                <div>
                  <h2 id="activity-h">Answers per {data.hourly ? 'hour' : 'day'}</h2>
                  <p>Questions the chat answered, and requests to the AI provider that failed</p>
                </div>
              </div>
              <div className="card-pad" style={{ paddingTop: 0 }}>
                <ActivityChart points={data.timeline} hourly={data.hourly} />
              </div>
            </section>

            <section className="card" aria-labelledby="quality-h">
              <div className="card-head">
                <div>
                  <h2 id="quality-h">Answer quality</h2>
                  <p>Average quality judge scores, 1 to 5</p>
                </div>
              </div>
              <dl className="quality-list">
                <div><dt>Groundedness</dt><dd>{formatScore(quality.groundedness)}</dd>
                  <span className="muted tiny">facts come from the sources</span></div>
                <div><dt>Relevance</dt><dd>{formatScore(quality.relevance)}</dd>
                  <span className="muted tiny">answers what was asked</span></div>
                <div><dt>Completeness</dt><dd>{formatScore(quality.completeness)}</dd>
                  <span className="muted tiny">uses everything the sources offer</span></div>
                <div><dt>Scored low</dt><dd>{quality.flagged}</dd>
                  <span className="muted tiny"><Link to="/admin/conversations?filter=review">sent to Needs review</Link></span></div>
                <div><dt>Search match</dt><dd>{chat.median_top_score == null ? '—' : chat.median_top_score.toFixed(2)}</dd>
                  <span className="muted tiny">median best similarity; low means the index may not cover the questions</span></div>
              </dl>
            </section>
          </div>

          <section className="card" aria-labelledby="models-h">
            <div className="card-head">
              <div>
                <h2 id="models-h">By model</h2>
                <p>Chat answers per model, to compare speed, cost and quality after switching</p>
              </div>
            </div>
            {data.models.length > 0 ? (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr><th>Model</th><th className="num">Answers</th><th className="num">Failed</th>
                      <th className="num">Median response</th><th className="num">First words</th>
                      <th className="num">Tokens per answer</th><th className="num">Groundedness</th></tr>
                  </thead>
                  <tbody>
                    {data.models.map((m) => (
                      <tr key={`${m.provider}/${m.model}`}>
                        <td className="mono">{m.model}</td>
                        <td className="num">{(m.calls - m.errors).toLocaleString('en-US')}</td>
                        <td className="num">{m.errors}</td>
                        <td className="num">{formatMs(m.p50_ms)}</td>
                        <td className="num">{formatMs(m.p50_first_token_ms)}</td>
                        <td className="num">{formatTokens(m.avg_input_tokens)} in · {formatTokens(m.avg_output_tokens)} out</td>
                        <td className="num">{formatScore(m.groundedness)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <div className="empty">No chat answers in this period.</div>}
          </section>

          <section className="card" aria-labelledby="recent-calls-h">
            <div className="card-head">
              <div>
                <h2 id="recent-calls-h">Recent calls</h2>
                <p>The latest requests to the AI provider, newest first</p>
              </div>
            </div>
            {data.recent.length > 0 ? (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr><th>When</th><th>Call</th><th>Model</th><th>Result</th><th className="num">Search</th>
                      <th className="num">First words</th><th className="num">Total</th><th className="num">Tokens in / out</th>
                      <th className="num">Grounded</th><th /></tr>
                  </thead>
                  <tbody>
                    {data.recent.map((t) => (
                      <tr key={t.id}>
                        <td className="nowrap">{formatWhen(t.at)}</td>
                        <td className="nowrap">{KIND_LABELS[t.kind] || t.kind}</td>
                        <td className="mono tiny nowrap">{t.model || '—'}</td>
                        <td>
                          {t.status === 'ok'
                            ? <span className="chip good">✓ OK</span>
                            : <span className="chip bad" title={t.error || undefined}>✕ Failed</span>}
                          {t.error && <div className="tiny muted trace-error">{t.error}</div>}
                        </td>
                        <td className="num">{formatMs(t.search_ms)}</td>
                        <td className="num">{formatMs(t.first_token_ms)}</td>
                        <td className="num">{formatMs(t.total_ms)}</td>
                        <td className="num nowrap">
                          {t.input_tokens != null ? `${formatTokens(t.input_tokens)} / ${formatTokens(t.output_tokens)}` : '—'}
                        </td>
                        <td className="num">{t.kind === 'preview' ? '' : t.groundedness ?? '—'}</td>
                        <td>
                          {t.conversation_id && (
                            <Link className="small nowrap" to={`/admin/conversations/${t.conversation_id}${t.message_id ? `#m-${t.message_id}` : ''}`}>
                              Open
                            </Link>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <div className="empty">No calls yet. They appear here as soon as someone asks the assistant a question.</div>}
          </section>
        </>
      )}
    </Page>
  );
};

export default Observability;
