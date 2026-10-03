import React from 'react';
import ReactDOM from 'react-dom/client';
// Bradley's site is set in Lato; bundled here so the widget matches it even offline
import '@fontsource/lato/latin-400.css';
import '@fontsource/lato/latin-700.css';
import './index.css';
import App from './App';

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
