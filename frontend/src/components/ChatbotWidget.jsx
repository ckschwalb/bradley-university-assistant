import React, { useState, useRef, useEffect } from 'react';
import ChatMessage from './ChatMessage';
import StartScreen from './StartScreen';
import { getStatus, getSuggestions, MAX_MESSAGE_CHARS, streamChat } from '../lib/api';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faArrowRight, faCommentDots, faGear, faMinus, faUpRightAndDownLeftFromCenter, faDownLeftAndUpRightToCenter } from '@fortawesome/free-solid-svg-icons';
import './ChatbotWidget.css';

// Phones get the launch button only: the chat window fills their screen width
const startsOpen = () =>
  typeof window.matchMedia !== 'function' || !window.matchMedia('(max-width: 520px)').matches;

const REPLY_TOP_GAP = 12; // px of space kept above the start of a reply

// The window's title bar: the name, a Demo chip while there's no API key (it opens the key form),
// and buttons for the admin center, enlarging or shrinking the window, and minimizing
const Header = ({ demo, onDemoClick, expanded, onToggleExpand, onMinimize }) => (
  <div className="chatbot-header">
    <div className="chatbot-title">
      <h3>Bradley AI Assistant</h3>
      {demo && (
        <button type="button" className="mode-chip" onClick={onDemoClick} title="Add your own API key for full answers">
          Demo
        </button>
      )}
    </div>
    <div className="header-actions">
      <a className="admin-button" href="/admin" title="Admin center">
        <FontAwesomeIcon icon={faGear} />
        <span>Admin</span>
      </a>
      <button
        className="expand-button"
        onClick={onToggleExpand}
        aria-label={expanded ? 'Shrink chat window' : 'Enlarge chat window'}
        title={expanded ? 'Shrink' : 'Enlarge'}
      >
        <FontAwesomeIcon icon={expanded ? faDownLeftAndUpRightToCenter : faUpRightAndDownLeftFromCenter} />
      </button>
      <button className="close-button" onClick={onMinimize} aria-label="Minimize chat" title="Minimize">
        <FontAwesomeIcon icon={faMinus} />
      </button>
    </div>
  </div>
);

const ChatbotWidget = () => {
  const [isOpen, setIsOpen] = useState(startsOpen);
  const [messages, setMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false); // from sending until the answer is complete
  const [conversationId, setConversationId] = useState(null);
  const [started, setStarted] = useState(false); // past the start screen
  const [keyFormFirst, setKeyFormFirst] = useState(false); // reopen the start screen at the key form
  const [expanded, setExpanded] = useState(false);
  const [status, setStatus] = useState(null);
  const [suggestions, setSuggestions] = useState([]);
  const messagesRef = useRef(null);
  const inputRef = useRef(null);
  const scrolledToReply = useRef(null);

  const last = messages[messages.length - 1];
  const waitingForFirstWord = isLoading && last?.sender === 'user';

  // Your own message and the typing indicator scroll to the bottom. A reply scrolls to where it
  // starts once, when its first words arrive, so you read it from the top as it streams in.
  useEffect(() => {
    const container = messagesRef.current;
    if (!container) return;
    if (last?.sender !== 'bot') {
      container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
      return;
    }
    if (scrolledToReply.current === last.key) return;
    const reply = Array.from(container.children).find((el) => el.dataset.messageKey === last.key);
    if (!reply) return;
    scrolledToReply.current = last.key;
    // offsetTop is in the container's own pixels; bounding-rect math isn't, because the window is
    // drawn with CSS zoom, which would land the scroll past the top of the bubble
    container.scrollTo({ top: reply.offsetTop - REPLY_TOP_GAP, behavior: 'smooth' });
  }, [messages, last]);

  const refreshStatus = () => getStatus().then(setStatus).catch(() => setStatus(null));

  useEffect(() => {
    // Which AI provider answers, or demo mode if none is set up
    if (isOpen) {
      refreshStatus();
      getSuggestions().then(setSuggestions).catch(() => setSuggestions([]));  // no pills if unavailable
    }
  }, [isOpen]);

  const demo = Boolean(status && status.demo_mode);

  useEffect(() => {
    // One line until the text wraps, then grow to a second line; past that it scrolls
    const el = inputRef.current;
    if (!el) return;

    el.style.height = 'auto'; // let scrollHeight reflect the text alone
    const style = window.getComputedStyle(el);
    const lineHeight = parseFloat(style.lineHeight) || 21;
    const padding = (parseFloat(style.paddingTop) || 0) + (parseFloat(style.paddingBottom) || 0);
    el.style.height = `${Math.min(el.scrollHeight, lineHeight * 2 + padding)}px`;
  }, [inputMessage]);

  const updateMessage = (key, changes) =>
    setMessages((prev) => prev.map((m) => (m.key === key ? { ...m, ...changes } : m)));

  const sendMessage = async () => {
    if (!inputMessage.trim()) return;

    const now = Date.now();
    const userKey = `user-${now}`;
    const replyKey = `bot-${now}`;
    setMessages((prev) => [...prev, {
      key: userKey, id: null, text: inputMessage, sender: 'user', timestamp: new Date().toLocaleTimeString(),
    }]);
    const currentInput = inputMessage;
    setInputMessage('');
    setIsLoading(true);

    // The reply appears with its first words, then grows as the rest arrives
    let started = false;
    const onDelta = (text) => {
      if (!started) {
        started = true;
        setMessages((prev) => [...prev, {
          key: replyKey, id: null, text, sender: 'bot', timestamp: new Date().toLocaleTimeString(),
          sources: [], noFeedback: true, streaming: true,
        }]);
      } else {
        setMessages((prev) => prev.map((m) => (m.key === replyKey ? { ...m, text: m.text + text } : m)));
      }
    };

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 130000); // outlasts the server: 2 provider attempts of 60s each
    try {
      const data = await streamChat({ message: currentInput, conversationId, onDelta, signal: controller.signal });

      if (data.conversation_id && data.conversation_id !== conversationId) {
        setConversationId(data.conversation_id);
      }
      if (data.demo !== demo) refreshStatus(); // a key was added or removed elsewhere
      const saved = Boolean(data.assistant_message_id);
      if (saved) updateMessage(userKey, { id: data.user_message_id });
      const final = {
        // Setup notices and provider errors aren't saved, so they have no id and no feedback buttons
        id: data.assistant_message_id || null,
        text: data.response,
        sources: data.sources || [],
        noFeedback: !saved,
        streaming: false,
        demo: data.demo,
        model: data.model,
      };
      if (started) {
        updateMessage(replyKey, final);
      } else {
        setMessages((prev) => [...prev, { key: replyKey, sender: 'bot', timestamp: new Date().toLocaleTimeString(), ...final }]);
      }
    } catch (error) {
      console.error('Error sending message:', error);

      let errorText = 'Sorry, I encountered an error. Please try again.';
      if (error.name === 'AbortError') {
        errorText = 'The request timed out. Please try again with a shorter question.';
      } else if (error.message.includes('Failed to fetch')) {
        errorText = 'Unable to connect to the server. Please check your internet connection and try again.';
      } else if (error.message.includes('500')) {
        errorText = 'Server error occurred. The AI assistant may be temporarily unavailable. Please try again in a moment.';
      }
      // A half-streamed reply is replaced by the error: nothing was saved
      setMessages((prev) => [...prev.filter((m) => m.key !== replyKey), {
        key: `error-${Date.now()}`, id: null, text: errorText, sender: 'bot',
        timestamp: new Date().toLocaleTimeString(), sources: [], noFeedback: true,
      }]);
    } finally {
      clearTimeout(timeoutId);
      setIsLoading(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  // Put the full request in the box for the user to edit, with the cursor at the end
  const handleSuggestionClick = (suggestion) => {
    setInputMessage(suggestion.prompt);
    setTimeout(() => {
      const input = inputRef.current;
      if (!input) return;
      input.focus();
      input.setSelectionRange(suggestion.prompt.length, suggestion.prompt.length);
    }, 0);
  };

  const handleOpenChatbot = () => {
    // The start screen shows in the panel the first time it opens
    setIsOpen(true);
  };

  const toggleExpanded = () => setExpanded((prev) => !prev);

  const handleMinimizeChatbot = () => {
    setIsOpen(false);
  };


  return (
    <div className="chatbot-widget">
      {isOpen && !started && (
        <div className={`chatbot-container${expanded ? ' expanded' : ''}`}>
          <Header demo={demo} onDemoClick={() => setKeyFormFirst(true)} expanded={expanded}
                  onToggleExpand={toggleExpanded} onMinimize={handleMinimizeChatbot} />
          <StartScreen
            key={keyFormFirst ? 'key-form' : 'welcome'}
            status={status}
            startWithKeyForm={keyFormFirst}
            onStart={() => { setStarted(true); setKeyFormFirst(false); }}
            onKeySaved={refreshStatus}
          />
        </div>
      )}

      {!isOpen && (
        <button
          className="chatbot-toggle"
          onClick={handleOpenChatbot}
          aria-label="Open Bradley AI Assistant"
        >
          <FontAwesomeIcon icon={faCommentDots} />
          <span>Ask Bradley</span>
        </button>
      )}

      {isOpen && started && (
        <div className={`chatbot-container${expanded ? ' expanded' : ''}`}>
          <Header demo={demo} onDemoClick={() => { setStarted(false); setKeyFormFirst(true); }} expanded={expanded}
                  onToggleExpand={toggleExpanded} onMinimize={handleMinimizeChatbot} />

          <div className="chatbot-messages" ref={messagesRef}>
            {status && status.indexed_chunks === 0 && (
              <div className="setup-notice">
                The Bradley website hasn't been indexed yet, so answers won't include university information.
                The crawler builds the index on first start; progress is in the admin center under <strong>Knowledge</strong>.
              </div>
            )}

            <div className="preview-notice">
              <span className="notice-badge">Notice</span>
              <span className="notice-text">University-sponsored, not live</span>
            </div>

            {messages.map((message) => (
              <div key={message.key} data-message-key={message.key}>
                <ChatMessage message={message} conversationId={conversationId} />
              </div>
            ))}

            {waitingForFirstWord && (
              <div className="typing-indicator" role="status" aria-label="The assistant is answering">
                <span></span>
                <span></span>
                <span></span>
              </div>
            )}
          </div>
          
          <div className="chatbot-input">
            {messages.length === 0 && suggestions.length > 0 && (
              <div className="suggestions-container">
                {suggestions.map((suggestion) => (
                  <button
                    key={suggestion.label}
                    className="suggestion-pill"
                    onClick={() => handleSuggestionClick(suggestion)}
                    disabled={isLoading}
                    title={suggestion.prompt}
                  >
                    {suggestion.label}
                  </button>
                ))}
              </div>
            )}
            <div className="input-pill">
              <textarea
                ref={inputRef}
                rows={1}
                value={inputMessage}
                onChange={(e) => setInputMessage(e.target.value)}
                onKeyPress={handleKeyPress}
                placeholder="Type your message..."
                maxLength={MAX_MESSAGE_CHARS}
                disabled={isLoading}
              />
              <button
                className="send-button"
                onClick={sendMessage}
                disabled={isLoading || !inputMessage.trim()}
                aria-label="Send message"
              >
                <FontAwesomeIcon icon={faArrowRight} />
              </button>
            </div>
            {inputMessage.length >= MAX_MESSAGE_CHARS * 0.8 && (
              <div className="char-count" role="status">{inputMessage.length} / {MAX_MESSAGE_CHARS}</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default ChatbotWidget;
