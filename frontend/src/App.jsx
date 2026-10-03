import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import ChatbotWidget from './components/ChatbotWidget';
import SiteBackdrop from './components/SiteBackdrop';
import AdminApp from './admin/AdminApp';
import Overview from './admin/Overview';
import Conversations from './admin/Conversations';
import Knowledge from './admin/Knowledge';
import Assistant from './admin/Assistant';
import Observability from './admin/Observability';
import './App.css';

function App() {
  return (
    <Router>
      <div className="App">
        <Routes>
          <Route path="/admin" element={<AdminApp />}>
            <Route index element={<Overview />} />
            <Route path="conversations" element={<Conversations />} />
            <Route path="conversations/:id" element={<Conversations />} />
            <Route path="knowledge" element={<Knowledge />} />
            <Route path="assistant" element={<Assistant />} />
            <Route path="observability" element={<Observability />} />
            <Route path="*" element={<Navigate to="/admin" replace />} />
          </Route>
          <Route path="*" element={<><SiteBackdrop /><ChatbotWidget /></>} />
        </Routes>
      </div>
    </Router>
  );
}

export default App;
