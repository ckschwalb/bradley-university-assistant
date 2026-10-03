import React, { useEffect, useState } from 'react';
import { getProviders, saveApiKey } from '../lib/api';

// The first screen in the chat window: what the assistant is, and how it answers. Without an API
// key the chat runs in demo mode (quoting Bradley's website); anyone can add a key here instead.
// The server requires an admin token (ADMIN_TOKEN) for settings; signing in at /admin stores it for this page too
const readable = (err) => (err.message === 'Admin token required'
  ? 'Saving a key needs the admin token. Sign in at /admin first, then come back.'
  : err.message);

const StartScreen = ({ status, startWithKeyForm = false, onStart, onKeySaved }) => {
  const [keyForm, setKeyForm] = useState(startWithKeyForm);
  const [providers, setProviders] = useState([]);
  const [provider, setProvider] = useState('anthropic');
  const [apiKey, setApiKey] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!keyForm || providers.length) return;
    getProviders()
      .then((data) => {
        setProviders(data.providers);
        if (data.provider) setProvider(data.provider);
      })
      .catch((err) => setError(err.message === 'Admin token required' ? readable(err)
        : "Couldn't load the AI providers. Is the server running?"));
  }, [keyForm, providers.length]);

  const save = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError('');
    try {
      await saveApiKey(provider, apiKey.trim());
      setApiKey('');
      await onKeySaved();
      onStart();
    } catch (err) {
      setError(readable(err));
    } finally {
      setSaving(false);
    }
  };

  if (keyForm) {
    const chosen = providers.find((p) => p.id === provider);
    return (
      <form className="start-content" onSubmit={save}>
        <h3>Use your own API key</h3>
        <p className="start-small">
          The assistant writes full answers with Claude, OpenAI, or Gemini. The key is checked with the provider, then
          saved in this app's database and used for every chat until it's removed in the admin center.
        </p>
        <div className="key-fields">
          <select aria-label="AI provider" value={provider} onChange={(e) => setProvider(e.target.value)}>
            {(providers.length ? providers : [{ id: 'anthropic', label: 'Claude (Anthropic)' }]).map((p) => (
              <option key={p.id} value={p.id}>{p.label}</option>
            ))}
          </select>
          <input
            type="password"
            autoComplete="off"
            aria-label="API key"
            placeholder="Paste your API key"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </div>
        {chosen && chosen.key_url && (
          <a className="start-link" href={chosen.key_url} target="_blank" rel="noopener noreferrer">Get a key ↗</a>
        )}
        {error && <p className="start-error" role="alert">{error}</p>}
        <div className="start-actions">
          <button type="submit" className="start-button" disabled={saving || !apiKey.trim()}>
            {saving ? 'Checking…' : 'Save and start'}
          </button>
          <button type="button" className="link-button" onClick={() => { setKeyForm(false); setError(''); }}>
            Back
          </button>
        </div>
      </form>
    );
  }

  const demo = !status || status.demo_mode;
  return (
    <div className="start-content">
      <h3>Welcome to the Bradley AI Assistant.</h3>
      <p>
        A working prototype developed in collaboration with Bradley University. Not officially launched.
      </p>
      <p>Conversations are saved for review.</p>
      <button type="button" className="start-button" onClick={onStart}>
        {demo ? 'Try the demo' : 'Start chatting'}
      </button>
      <p className="start-small">
        {demo ? 'The demo quotes Bradley\'s website. ' : `Answers by ${status.provider_label.split(' ')[0]}. `}
        <button type="button" className="link-button" onClick={() => setKeyForm(true)}>
          {demo ? 'Add your own API key' : 'Use a different API key'}
        </button>
        {demo && ' for full answers.'}
      </p>
    </div>
  );
};

export default StartScreen;
