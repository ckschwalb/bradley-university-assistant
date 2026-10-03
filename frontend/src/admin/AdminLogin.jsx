import React, { useState } from 'react';
import { setAdminToken } from '../lib/adminAuth';
import { request } from '../lib/request';

// Shown when the server has an ADMIN_TOKEN and this browser hasn't entered it (or entered the wrong one)
const AdminLogin = ({ onSignedIn }) => {
  const [token, setToken] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    setAdminToken(token.trim());
    try {
      await request('/api/admin/crawl/status'); // any admin call: it fails with 401 if the token is wrong
      onSignedIn();
    } catch (err) {
      setError(err.message === 'Admin token required' ? 'That token was not accepted.' : err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="admin admin-login">
      <main className="admin-main">
        <form className="card card-pad admin-login-card" onSubmit={submit}>
          <h1>Admin sign-in</h1>
          <p>This server requires an admin token (the <code>ADMIN_TOKEN</code> it was started with).</p>
          <label className="field">
            Admin token
            <input className="input" type="password" autoComplete="current-password" autoFocus
              value={token} onChange={(e) => setToken(e.target.value)} />
          </label>
          {error && <div className="callout bad" role="alert">{error}</div>}
          <div className="row">
            <button className="btn primary" type="submit" disabled={busy || !token.trim()}>Sign in</button>
            <a className="btn ghost" href="/">Back to chat</a>
          </div>
        </form>
      </main>
    </div>
  );
};

export default AdminLogin;
