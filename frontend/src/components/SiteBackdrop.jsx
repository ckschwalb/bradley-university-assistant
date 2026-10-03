import React from 'react';
import './SiteBackdrop.css';

// The live page shown behind the chat widget, so the demo looks like it's running on the real site.
// Override with ?site=<url>, or ?site=off to fall back to the static screenshot (e.g. when offline).
const DEFAULT_SITE = import.meta.env.VITE_DEMO_SITE_URL || 'https://www.bradley.edu/';

const siteUrl = () => {
  const requested = new URLSearchParams(window.location.search).get('site');
  if (requested === 'off') return null;
  if (requested && /^https?:\/\//i.test(requested)) return requested;
  return DEFAULT_SITE;
};

const SiteBackdrop = () => {
  const url = siteUrl();
  if (!url) return null;

  return (
    <div className="site-backdrop">
      {/* No allow-top-navigation: links on the page can't navigate away from the demo */}
      <iframe
        src={url}
        title="Bradley University website"
        sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox"
        referrerPolicy="no-referrer"
      />
    </div>
  );
};

export default SiteBackdrop;
