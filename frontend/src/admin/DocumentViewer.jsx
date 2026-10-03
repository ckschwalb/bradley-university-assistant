import React, { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { formatWhen, typeLabel } from './api';
import { useApi } from './useApi';

// Wrap matches of `term` in <mark>, inside plain text children only
const highlight = (children, term) => {
  if (!term) return children;
  const pattern = new RegExp(`(${term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
  return React.Children.map(children, (child) => {
    if (typeof child !== 'string') return child;
    return child.split(pattern).map((part, i) => (i % 2 ? <mark key={i}>{part}</mark> : part));
  });
};

const DocumentViewer = ({ docId, onClose }) => {
  const { data: doc, error } = useApi(`/api/admin/data-sources/${docId}`);
  const [term, setTerm] = useState('');
  const closeRef = useRef(null);

  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const withMarks = (Tag) => {
    const Marked = ({ node, children, ...props }) => <Tag {...props}>{highlight(children, term)}</Tag>;
    return Marked;
  };
  const components = {
    p: withMarks('p'), li: withMarks('li'), h1: withMarks('h3'), h2: withMarks('h3'), h3: withMarks('h4'),
    td: withMarks('td'), strong: withMarks('strong'), em: withMarks('em'),
    a: ({ node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer">{highlight(props.children, term)}</a>,
  };

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="doc-title">
        <div className="modal-head">
          <div style={{ minWidth: 0 }}>
            <h2 id="doc-title">{doc ? doc.title : 'Loading…'}</h2>
            {doc && (
              <p className="small muted" style={{ marginTop: 4 }}>
                {typeLabel(doc.source_type)} · updated {formatWhen(doc.last_updated)}
                {doc.chunks > 1 && ` · stored as ${doc.chunks} search chunks`} ·{' '}
                <a href={doc.url} target="_blank" rel="noopener noreferrer">Open the page ↗</a>
              </p>
            )}
          </div>
          <button ref={closeRef} type="button" className="btn sm" onClick={onClose}>Close</button>
        </div>
        <div className="modal-body">
          {error && <div className="callout bad">{error}</div>}
          {doc && (
            <>
              <input
                className="input sm"
                type="search"
                placeholder="Find in this page"
                aria-label="Find in this page"
                value={term}
                onChange={(e) => setTerm(e.target.value)}
              />
              <div className="doc-text answer-text">
                <ReactMarkdown components={components}>{doc.full_content || ''}</ReactMarkdown>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default DocumentViewer;
