import React, { useCallback, useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Page, useAdmin } from './AdminApp';
import { api, plural } from './api';

const markdownLinks = { a: ({ node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer">{props.children}</a> };

const ModelSettings = () => {
  const { llm, setLlm, notify } = useAdmin();
  const [provider, setProvider] = useState(null);
  const [model, setModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [editingKey, setEditingKey] = useState(false);
  const [models, setModels] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const current = llm && llm.providers.find((p) => p.id === (provider || llm.provider));
  const saved = llm && llm.providers.find((p) => p.id === llm.provider);

  const loadModels = useCallback(async (providerId, key) => {
    const result = await api('/api/settings/llm/models', { method: 'POST', body: { provider: providerId, api_key: key || undefined } });
    setModels(result.models);
    return result;
  }, []);

  // Start from what's saved, and list the models whenever a provider with a saved key is chosen
  useEffect(() => {
    if (!llm || provider) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- seeds the form from the saved settings once they load
    setProvider(llm.provider);
  }, [llm, provider]);

  useEffect(() => {
    if (!current) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- resets the form whenever another provider is chosen
    setModel(current.model);
    setModels([]);
    setApiKey('');
    setEditingKey(!current.has_key);
    setError('');
    if (current.has_key) loadModels(current.id).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current && current.id, current && current.has_key, loadModels]);

  if (!llm || !current) return null;

  const switching = current.id !== llm.provider || !saved.has_key;
  const dirty = switching || Boolean(apiKey) || model !== current.model;
  const options = models.includes(model) || !model ? models : [model, ...models];

  const test = async () => {
    setBusy(true);
    setError('');
    try {
      const result = await loadModels(current.id, apiKey);
      if (!result.models.includes(model) && result.models.length) {
        setModel(result.models.includes(result.default_model) ? result.default_model : result.models[0]);
      }
      notify(`The key works. ${plural(result.models.length, 'model')} available.`);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (!apiKey && !current.has_key) {
      setError(`Paste a ${current.label.split(' ')[0]} API key first.`);
      return;
    }
    setBusy(true);
    setError('');
    try {
      if (apiKey) await loadModels(current.id, apiKey); // check the key before saving it, so a typo can't break the chat
      const result = await api('/api/settings/llm', {
        method: 'PUT',
        body: { provider: current.id, model: model || undefined, api_key: apiKey || undefined },
      });
      setLlm(result);
      setProvider(result.provider);
      notify(`Chats are now answered by ${current.label.split(' ')[0]} · ${model || current.model}.`);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const removeKey = async () => {
    if (!window.confirm(`Remove the saved ${current.label} API key?`)) return;
    try {
      setLlm(await api('/api/settings/llm', { method: 'PUT', body: { provider: current.id, api_key: '' } }));
      notify('API key removed.');
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <section className="card" aria-labelledby="model-h" style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div className="model-row">
        <h2 id="model-h">AI model</h2>
        <select className="select sm" aria-label="Provider" value={current.id} onChange={(e) => setProvider(e.target.value)}>
          {llm.providers.map((p) => (
            <option key={p.id} value={p.id}>{p.label}{p.has_key ? '' : ' · needs key'}</option>
          ))}
        </select>
        <select className="select sm mono" aria-label="Model" value={model} onChange={(e) => setModel(e.target.value)} style={{ fontSize: 13 }}>
          {options.length === 0 && <option value={model}>{model}</option>}
          {options.map((m) => <option key={m} value={m}>{m}{m === current.default_model ? ' (default)' : ''}</option>)}
        </select>
        {editingKey ? (
          <input
            className="input sm grow"
            type="password"
            autoComplete="off"
            aria-label={`${current.label} API key`}
            placeholder={current.has_key ? `Paste a new key to replace ${current.key_hint}` : `Paste a ${current.label.split(' ')[0]} API key`}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            style={{ minWidth: 220 }}
          />
        ) : (
          <span className="row small muted" style={{ gap: 2 }}>
            Key <span className="mono" style={{ marginLeft: 4 }}>{current.key_hint}</span>
            <button type="button" className="link-btn" onClick={() => setEditingKey(true)}>Replace</button>
            <button type="button" className="link-btn" onClick={removeKey}>Remove</button>
          </span>
        )}
        {!current.has_key && (
          <a className="small" href={current.key_url} target="_blank" rel="noopener noreferrer">Get a key ↗</a>
        )}
        <span className="grow" />
        {dirty ? (
          <>
            <button type="button" className="btn sm" onClick={test} disabled={busy || (!apiKey && !current.has_key)}>Test</button>
            <button type="button" className="btn sm primary" onClick={save} disabled={busy}>
              {busy ? 'Saving…' : switching ? 'Save and switch' : 'Save'}
            </button>
          </>
        ) : (
          <span className="chip good">● In use</span>
        )}
      </div>
      {error && <div className="callout bad">{error}</div>}
      <JudgeRow />
    </section>
  );
};

// Whether a second model call grades each answer (backend/evaluator.py), and with which model.
// A row in the AI model card, since the judge uses the chat provider's key.
const JudgeRow = () => {
  const { llm, active, notify } = useAdmin();
  const [judge, setJudge] = useState(null);
  const [model, setModel] = useState('');
  const [models, setModels] = useState([]);
  const [error, setError] = useState('');

  useEffect(() => {
    api('/api/settings/judge').then((j) => { setJudge(j); setModel(j.model || ''); }).catch((e) => setError(e.message));
  }, [llm]);

  const activeId = active && active.id;
  useEffect(() => {
    if (!activeId) return;
    api('/api/settings/llm/models', { method: 'POST', body: { provider: activeId } })
      .then((result) => setModels(result.models)).catch(() => setModels([]));
  }, [activeId]);

  if (!judge || !active) return error ? <div className="callout bad">{error}</div> : null;

  const save = async (changes) => {
    setError('');
    try {
      const next = await api('/api/settings/judge', { method: 'PUT', body: { enabled: judge.enabled, model, ...changes } });
      setJudge(next);
      setModel(next.model);
      notify(next.enabled ? `Answers are now graded by ${next.model}.` : 'The quality judge is off.');
    } catch (e) {
      setError(e.message);
    }
  };

  const options = models.includes(model) || !model ? models : [model, ...models];
  return (
    <>
      <div className="model-row judge-row">
        <h2 title="After each answer, one more request scores its groundedness, relevance and completeness from 1 to 5. Low scores go to Needs review; averages are under Observability.">
          Quality judge
        </h2>
        <label className="row small" style={{ gap: 6 }}>
          <input type="checkbox" checked={judge.enabled} onChange={(e) => save({ enabled: e.target.checked })} />
          Grade every answer
        </label>
        <select className="select sm mono" aria-label="Judge model" value={model} disabled={!judge.enabled}
          onChange={(e) => setModel(e.target.value)} style={{ fontSize: 13 }}>
          {options.length === 0 && <option value={model}>{model}</option>}
          {options.map((m) => <option key={m} value={m}>{m}{m === active.model ? ' (chat model)' : ''}</option>)}
        </select>
        <span className="grow" />
        {model !== judge.model
          ? <button type="button" className="btn sm primary" onClick={() => save({})}>Save</button>
          : judge.enabled && <span className="chip good">● Grading</span>}
      </div>
      {error && <div className="callout bad">{error}</div>}
    </>
  );
};

const PromptEditor = () => {
  const { notify } = useAdmin();
  const [prompt, setPrompt] = useState(null); // {content, is_default, saved_at, default_content}
  const [draft, setDraft] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [question, setQuestion] = useState('');
  const [preview, setPreview] = useState(null);
  const [previewing, setPreviewing] = useState(false);

  const show = useCallback((result) => {
    setPrompt(result);
    setDraft(result.content);
  }, []);

  useEffect(() => {
    api('/api/admin/system-prompt').then(show).catch((e) => setError(e.message));
  }, [show]);

  if (!prompt) return error ? <div className="callout bad">{error}</div> : null;

  const changed = draft !== prompt.content;
  const lines = draft.split('\n').length;

  const save = async () => {
    setSaving(true);
    setError('');
    try {
      show(await api('/api/admin/system-prompt', { method: 'POST', body: { content: draft } }));
      setPreview(null);
      notify('Saved. It applies to the next message.');
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const runPreview = async (e) => {
    e.preventDefault();
    setPreviewing(true);
    setPreview(null);
    setError('');
    try {
      const result = await api('/api/admin/system-prompt/preview', { method: 'POST', body: { content: draft, question } });
      setPreview({ ...result, unchanged: !changed });
    } catch (err) {
      setPreview({ error: err.message });
    } finally {
      setPreviewing(false);
    }
  };

  return (
    <section className="card" aria-labelledby="prompt-h">
      <div className="prompt-head">
        <h2 id="prompt-h" style={{ fontSize: 17, fontWeight: 700 }}>Instructions</h2>
        <div className="row">
          <button type="button" className="btn" onClick={() => setDraft(prompt.default_content)}
            disabled={draft === prompt.default_content || saving}>
            Use default
          </button>
          <button type="button" className="btn" onClick={() => setDraft(prompt.content)} disabled={!changed || saving}>
            Discard changes
          </button>
          <button type="button" className="btn primary" onClick={save} disabled={!changed || !draft.trim() || saving}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
      {error && <div className="callout bad" style={{ margin: '12px 20px 0' }}>{error}</div>}
      <div className="prompt-grid">
        <div className="prompt-editor">
          <textarea
            className="prompt-textarea"
            aria-label="System prompt"
            spellCheck={false}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <div className="row tiny muted" style={{ justifyContent: 'space-between' }}>
            <span>{plural(lines, 'line')} · {plural(draft.length, 'character')}</span>
            {!draft.includes('{context}') && (
              <span style={{ color: 'var(--warn-ink)' }}>No {'{context}'}: search results will be added at the end.</span>
            )}
          </div>
        </div>

        <aside className="try-panel" aria-labelledby="try-h">
          <h3 id="try-h">Try the draft</h3>
          <p className="small muted">Ask a question with these instructions before saving. Nothing is recorded.</p>
          <form onSubmit={runPreview} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <label className="field">
              Question
              <input className="input" type="text" value={question} onChange={(e) => setQuestion(e.target.value)}
                placeholder="e.g. Who chairs physical therapy?" />
            </label>
            <button type="submit" className="btn" disabled={previewing || !question.trim() || !draft.trim()}>
              {previewing ? 'Asking…' : 'Preview answer'}
            </button>
          </form>
          {preview && preview.error && <div className="callout bad">{preview.error}</div>}
          {preview && !preview.error && (
            <>
              <div className="try-answer">
                <h4>{preview.unchanged ? 'Answer' : 'With your draft'}</h4>
                <div className="answer-text"><ReactMarkdown components={markdownLinks}>{preview.draft}</ReactMarkdown></div>
              </div>
              {!preview.unchanged && (
                <details className="try-answer">
                  <summary style={{ cursor: 'pointer', fontWeight: 600, fontSize: 12 }}>With the saved instructions</summary>
                  <div className="answer-text" style={{ marginTop: 6 }}><ReactMarkdown components={markdownLinks}>{preview.active}</ReactMarkdown></div>
                </details>
              )}
              <p className="tiny muted">
                {preview.model} · sources: {preview.sources.map((s) => s.title).join(', ') || 'none found'}
              </p>
            </>
          )}
        </aside>
      </div>
    </section>
  );
};

const Assistant = () => (
  <Page title="Assistant" subtitle="Which AI writes the answers, and the instructions it follows">
    <ModelSettings />
    <PromptEditor />
  </Page>
);

export default Assistant;
