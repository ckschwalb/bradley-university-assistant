import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Page, useAdmin } from './AdminApp';
import { api, formatDay, formatWhen, plural, typeLabel } from './api';
import { crawlState, indexedItems, lastCrawlSummary, nextCrawlAt } from './crawl';
import DocumentViewer from './DocumentViewer';
import { useApi } from './useApi';

const TARGETS = [
  ['all', 'Website and course catalog', ['site', 'courses']],
  ['site', 'Website only', ['site']],
  ['courses', 'Course catalog only', ['courses']],
];
const INTERVALS = [6, 12, 24, 48, 168];
const PAGE_SIZE = 25;

const intervalLabel = (hours) => (hours % 24 === 0 && hours >= 48 ? plural(hours / 24, 'day') : plural(hours, 'hour'));
const shortUrl = (url) => url.replace('https://www.bradley.edu', '').replace('https://catalog.bradley.edu', 'catalog');

const CrawlControls = ({ crawl, onStarted }) => {
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState('all');
  const [force, setForce] = useState(false);
  const [error, setError] = useState('');
  const wrapRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => wrapRef.current && !wrapRef.current.contains(e.target) && setOpen(false);
    const escape = (e) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', escape);
    };
  }, [open]);

  const start = async () => {
    setError('');
    try {
      const result = await api('/api/admin/crawl/start', {
        method: 'POST',
        body: { force, targets: TARGETS.find(([id]) => id === target)[2] },
      });
      setOpen(false);
      setForce(false);
      onStarted(result.crawler_online
        ? 'Crawl requested. It starts within about 15 seconds.'
        : "Crawl requested. The crawler isn't running, so it starts once it is.");
    } catch (e) {
      setError(e.message);
    }
  };

  const busy = crawl && (crawl.status === 'running' || Boolean(crawl.requested_at));
  const summary = `${TARGETS.find(([id]) => id === target)[1]}${force ? ', full re-crawl' : ''}`;

  return (
    <div className="popover-wrap row" ref={wrapRef}>
      {error && <span className="small" style={{ color: 'var(--bad-ink)' }}>{error}</span>}
      <button type="button" className="btn" aria-expanded={open} onClick={() => setOpen((o) => !o)}>Crawl options</button>
      <button type="button" className="btn primary" onClick={start} disabled={busy} title={summary}>
        {crawl && crawl.status === 'running' ? 'Crawling…' : busy ? 'Starting soon…' : 'Crawl now'}
      </button>
      {open && (
        <div className="popover" role="dialog" aria-label="Crawl options">
          <fieldset style={{ border: 0, margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <legend className="label" style={{ marginBottom: 6 }}>What to crawl</legend>
            {TARGETS.map(([id, label]) => (
              <label key={id} className="radio-row">
                <input type="radio" name="crawl-target" checked={target === id} onChange={() => setTarget(id)} />
                {label}
              </label>
            ))}
          </fieldset>
          <label className="radio-row" style={{ alignItems: 'flex-start' }}>
            <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} style={{ marginTop: 4 }} />
            <span>
              Full re-crawl
              <span className="tiny muted" style={{ display: 'block', fontWeight: 400 }}>
                Re-embeds everything instead of only what changed. Takes about 20 minutes.
              </span>
            </span>
          </label>
          <button type="button" className="btn primary" onClick={start} disabled={busy}>Crawl now</button>
        </div>
      )}
    </div>
  );
};

const AutoCrawl = ({ crawl, onSaved }) => {
  const [error, setError] = useState('');
  const auto = crawl.auto_crawl;
  const options = INTERVALS.includes(auto.interval_hours) ? INTERVALS : [...INTERVALS, auto.interval_hours].sort((a, b) => a - b);

  const save = async (changes) => {
    setError('');
    try {
      await api('/api/admin/crawl/auto', { method: 'PUT', body: { ...auto, ...changes } });
      onSaved();
    } catch (e) {
      setError(e.message);
    }
  };

  const next = nextCrawlAt(crawl);
  return (
    <div className="row" style={{ gap: 12 }}>
      <label className="radio-row">
        <input
          type="checkbox"
          checked={auto.enabled}
          onChange={(e) => save({ enabled: e.target.checked })}
          style={{ width: 18, height: 18, accentColor: 'var(--accent)' }}
        />
        Auto-crawl every
      </label>
      <select
        className="select sm"
        aria-label="Auto-crawl interval"
        value={auto.interval_hours}
        disabled={!auto.enabled}
        onChange={(e) => save({ interval_hours: Number(e.target.value) })}
      >
        {options.map((h) => <option key={h} value={h}>{intervalLabel(h)}</option>)}
      </select>
      {auto.enabled && next && <span className="small muted">Next: {formatWhen(next)}</span>}
      {error && <span className="small" style={{ color: 'var(--bad-ink)' }}>{error}</span>}
    </div>
  );
};

const SearchTester = ({ onOpen }) => {
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState(params.get('test') || '');
  const [ran, setRan] = useState(null);
  const [results, setResults] = useState(null);
  const [error, setError] = useState('');
  const { data: overview } = useApi('/api/admin/overview');
  const samples = overview ? [...new Set(overview.recent_questions.map((q) => q.text))].slice(0, 3) : [];

  const run = useCallback(async (q) => {
    if (!q.trim()) return;
    setError('');
    setRan(q);
    setResults(null);
    try {
      setResults(await api('/api/admin/search-test', { method: 'POST', body: { query: q } }));
    } catch (e) {
      setError(e.message);
    }
  }, []);

  // ?test= drives the search, so "Test this search" links and the back button both work
  const tested = params.get('test') || '';
  const arrived = useRef(Boolean(tested));
  useEffect(() => {
    if (!tested) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the address bar drives the search box
    setQuery(tested);
    run(tested);
    if (arrived.current) {
      arrived.current = false;
      document.getElementById('test-h')?.scrollIntoView({ block: 'start' });
    }
  }, [tested, run]);

  const test = (q) => {
    if (!q.trim()) return;
    if (q.trim() === tested) { run(q.trim()); return; }
    setParams((p) => { const next = new URLSearchParams(p); next.set('test', q.trim()); return next; }, { replace: true });
  };

  const submit = (e) => {
    e.preventDefault();
    test(query);
  };

  const types = results ? [...new Set(results.map((r) => r.type))] : [];

  return (
    <section className="card card-pad" aria-labelledby="test-h" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div>
        <h2 id="test-h" style={{ fontSize: 17, fontWeight: 700 }}>Test a question</h2>
        <p className="muted small" style={{ marginTop: 2 }}>See exactly which sources the assistant would get, without asking the AI</p>
      </div>
      <form className="row" onSubmit={submit}>
        <input
          className="input grow"
          type="search"
          aria-label="Question"
          placeholder="Ask what a student would ask"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ minWidth: 200 }}
        />
        <button type="submit" className="btn" disabled={!query.trim()}>Search</button>
      </form>
      {samples.length > 0 && (
        <div className="row" style={{ gap: 6 }}>
          <span className="tiny muted">From recent chats:</span>
          {samples.map((s) => (
            <button key={s} type="button" className="pill" aria-pressed={ran === s} onClick={() => test(s)}>
              {s.length > 40 ? `${s.slice(0, 38)}…` : s}
            </button>
          ))}
        </div>
      )}
      {error && <div className="callout bad">{error}</div>}
      {ran && !results && !error && <p className="muted small">Searching…</p>}
      {results && results.length === 0 && <div className="callout warn">Nothing indexed matches this. Has a crawl finished?</div>}
      {results && results.length > 0 && (
        <>
          <ol className="results">
            {results.map((r, i) => (
              <li key={i}>
                <span className="mono tiny muted">#{i + 1}</span>
                <span style={{ minWidth: 0 }}>
                  {r.doc_id
                    ? <button type="button" className="doc-title-btn" onClick={() => onOpen(r.doc_id)}>{r.title}</button>
                    : <a className="result-title" href={r.url} target="_blank" rel="noopener noreferrer">{r.title}</a>}
                  <br />
                  <span className="url-cell">{shortUrl(r.url)}</span>
                </span>
                <span className="row" style={{ gap: 8 }}>
                  <span className="chip plain">{typeLabel(r.type)}</span>
                  <span className="mono tiny muted">{r.score.toFixed(3)}</span>
                </span>
              </li>
            ))}
          </ol>
          {types.length === 1 && results.length > 1 && (
            <div className="callout plain">
              All {results.length} results are {typeLabel(types[0]).toLowerCase()}. If the answer lives on another kind of page,
              find it under Browse sources and check that it's indexed.
            </div>
          )}
        </>
      )}
    </section>
  );
};

const Browse = ({ typeCounts, onOpen }) => {
  const [query, setQuery] = useState('');
  const [type, setType] = useState('');
  const [sort, setSort] = useState('title');
  const [rows, setRows] = useState([]);
  const [more, setMore] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async (offset) => {
    const params = new URLSearchParams({
      sort_by: sort, sort_order: sort === 'last_updated' ? 'desc' : 'asc', limit: PAGE_SIZE + 1, offset,
    });
    if (query.trim()) params.set('query', query.trim());
    if (type) params.set('source_type', type);
    try {
      const page = await api(`/api/admin/data-sources?${params}`);
      setMore(page.length > PAGE_SIZE);
      setRows((current) => (offset ? current : []).concat(page.slice(0, PAGE_SIZE)));
      setError('');
    } catch (e) {
      setError(e.message);
    }
  }, [query, type, sort]);

  useEffect(() => {
    const timer = setTimeout(() => load(0), 250);
    return () => clearTimeout(timer);
  }, [load]);

  return (
    <section className="card" aria-labelledby="browse-h">
      <div className="card-head" style={{ alignItems: 'center' }}>
        <h2 id="browse-h">Browse sources</h2>
        <div className="row">
          <input className="input sm" type="search" aria-label="Search sources" placeholder="Search titles and text"
            value={query} onChange={(e) => setQuery(e.target.value)} style={{ width: 240 }} />
          <select className="select sm" aria-label="Type" value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">All types</option>
            {Object.keys(typeCounts || {}).map((t) => <option key={t} value={t}>{typeLabel(t)}</option>)}
          </select>
          <select className="select sm" aria-label="Sort" value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="title">A to Z</option>
            <option value="last_updated">Recently updated</option>
            <option value="url">By address</option>
          </select>
        </div>
      </div>
      {error && <div className="callout bad" style={{ margin: '0 20px 12px' }}>{error}</div>}
      <table>
        <thead>
          <tr><th>Title</th><th>Type</th><th className="hide-sm">Address</th><th className="hide-sm">Updated</th></tr>
        </thead>
        <tbody>
          {rows.map((d) => (
            <tr key={d.id}>
              <td><button type="button" className="doc-title-btn" onClick={() => onOpen(d.id)}>{d.title}</button></td>
              <td><span className="chip plain">{typeLabel(d.source_type)}</span></td>
              <td className="hide-sm url-cell">{shortUrl(d.url)}</td>
              <td className="hide-sm muted nowrap">{d.last_updated ? formatDay(d.last_updated) : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && !error && <p className="empty">{query || type ? 'Nothing matches.' : 'Nothing is indexed yet.'}</p>}
      <div className="card-pad row small muted" style={{ justifyContent: 'space-between' }}>
        <span>{rows.length > 0 && `Showing ${rows.length}${more ? '+' : ''}. Click a title to read the exact text the assistant sees.`}</span>
        {more && <button type="button" className="btn sm" onClick={() => load(rows.length)}>Load more</button>}
      </div>
    </section>
  );
};

const Knowledge = () => {
  const { crawl, refreshCrawl, notify } = useAdmin();
  const [openDoc, setOpenDoc] = useState(null);
  const closeDoc = useCallback(() => setOpenDoc(null), []);

  // Keep the status live while this page is open
  useEffect(() => {
    refreshCrawl();
    const timer = setInterval(refreshCrawl, 5000);
    return () => clearInterval(timer);
  }, [refreshCrawl]);

  const state = crawlState(crawl);
  const counts = crawl ? Object.entries(crawl.type_counts || {}) : [];
  const largest = counts.length ? counts[0][1] : 1;

  return (
    <Page
      title="Knowledge"
      subtitle="What the assistant can draw on, and whether search finds it"
      actions={<CrawlControls crawl={crawl} onStarted={(message) => { notify(message); refreshCrawl(); }} />}
    >
      {crawl && (
        <section className="card status-strip" aria-label="Crawl status">
          <span className={`chip ${state.tone}`}>● {state.label}</span>
          <div className="grow" style={{ minWidth: 260 }}>
            <div style={{ fontWeight: 600 }}>{lastCrawlSummary(crawl)}</div>
            {crawl.error && <div className="small" style={{ color: 'var(--bad-ink)' }}>{crawl.error}</div>}
            {!crawl.crawler_online && (
              <div className="small muted">
                The crawler service isn't running, so crawls won't start. With Docker it starts with{' '}
                <code>docker compose up</code>; without Docker, run <code>python crawler_service.py</code> in <code>backend</code>.
              </div>
            )}
          </div>
          <AutoCrawl crawl={crawl} onSaved={() => { refreshCrawl(); notify('Auto-crawl saved.'); }} />
        </section>
      )}

      <div className="knowledge-split">
        <section className="card card-pad" aria-labelledby="mix-h" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
            <h2 id="mix-h" style={{ fontSize: 17, fontWeight: 700 }}>What's indexed</h2>
            {crawl && (
              <span className="small muted">
                {plural(indexedItems(crawl), 'item')} · {plural(crawl.total_chunks, 'search chunk')}
              </span>
            )}
          </div>
          {counts.map(([type, n]) => (
            <div key={type} className="mix-row">
              <span className="small">{typeLabel(type)}</span>
              <div className="mix-track"><div className="mix-bar" style={{ width: `${Math.max(1, (n / largest) * 100)}%` }} /></div>
              <span className="mix-value">{n.toLocaleString('en-US')}</span>
            </div>
          ))}
          {crawl && counts.length === 0 && <p className="muted">Nothing is indexed yet. Start a crawl to build the index.</p>}
          <p className="small muted">Courses come from catalog.bradley.edu; everything else from bradley.edu.</p>
        </section>

        <SearchTester onOpen={setOpenDoc} />
      </div>

      <Browse typeCounts={crawl && crawl.type_counts} onOpen={setOpenDoc} />

      {openDoc && <DocumentViewer docId={openDoc} onClose={closeDoc} />}
    </Page>
  );
};

export default Knowledge;
