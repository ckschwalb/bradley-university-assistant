import React, { useCallback, useEffect, useRef, useState } from 'react';
import { NavLink, Outlet, useOutletContext } from 'react-router-dom';
import { useApi } from './useApi';
import AdminLogin from './AdminLogin';
import { AUTH_REQUIRED_EVENT } from '../lib/adminAuth';
import './admin.css';

// What every screen can reach through useAdmin(): provider and crawl status, conversation counts,
// a way to refresh them, and a toast for confirmations.
export const useAdmin = () => useOutletContext();

export const Page = ({ title, subtitle, actions, children }) => {
  useEffect(() => {
    document.title = `${title} · Bradley Assistant admin`;
  }, [title]);
  return (
    <main className="admin-main">
      <div className="admin-page">
        <header className="admin-page-header">
          <div>
            <h1>{title}</h1>
            {subtitle && <p>{subtitle}</p>}
          </div>
          {actions && <div className="row">{actions}</div>}
        </header>
        {children}
      </div>
    </main>
  );
};

const AdminShell = () => {
  const { data: llm, setData: setLlm } = useApi('/api/settings/llm');
  const { data: crawl, reload: refreshCrawl } = useApi('/api/admin/crawl/status');
  const { data: conversations, reload: refreshCounts } = useApi('/api/admin/conversations');
  const counts = conversations && conversations.counts;
  const [toast, setToast] = useState('');
  const toastTimer = useRef(null);

  useEffect(() => {
    document.body.classList.add('admin-dashboard-body');
    return () => document.body.classList.remove('admin-dashboard-body');
  }, []);

  const notify = useCallback((message) => {
    setToast(message);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(''), 3500);
  }, []);

  const active = llm && llm.providers.find((p) => p.id === llm.provider && p.has_key);
  const context = { llm, setLlm, active, crawl, refreshCrawl, counts, refreshCounts, notify };

  return (
    <div className="admin">
      <nav className="admin-side" aria-label="Admin">
        <div className="admin-brand">
          <div className="admin-brand-text">
            <strong>Bradley Assistant</strong>
            <span>Admin</span>
          </div>
        </div>
        <a href="/" className="btn primary admin-open-chat">Open Chat</a>
        <div className="admin-nav">
          <NavLink to="/admin" end>Overview</NavLink>
          <NavLink to="/admin/conversations">
            Conversations {counts && <span className="count">{counts.all}</span>}
          </NavLink>
          <NavLink to="/admin/knowledge">Knowledge</NavLink>
          <NavLink to="/admin/assistant">Assistant</NavLink>
          <NavLink to="/admin/observability">Observability</NavLink>
        </div>
      </nav>

      <Outlet context={context} />

      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
};

// With ADMIN_TOKEN set on the server, the first refused request brings up the sign-in; a new
// token remounts the dashboard so every screen loads again with it.
const AdminApp = () => {
  const [signedInAs, setSignedInAs] = useState(0);
  const [needsToken, setNeedsToken] = useState(false);

  useEffect(() => {
    const show = () => setNeedsToken(true);
    window.addEventListener(AUTH_REQUIRED_EVENT, show);
    return () => window.removeEventListener(AUTH_REQUIRED_EVENT, show);
  }, []);

  if (needsToken) {
    return <AdminLogin onSignedIn={() => { setNeedsToken(false); setSignedInAs((n) => n + 1); }} />;
  }
  return <AdminShell key={signedInAs} />;
};

export default AdminApp;
