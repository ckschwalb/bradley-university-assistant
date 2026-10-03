/**
 * API client for the chat widget
 */
import { request } from './request';

export const MAX_MESSAGE_CHARS = 1000; // the server refuses longer questions

/**
 * Submit feedback for a conversation or message
 * @param {Object} feedbackData - Feedback data
 * @param {string} feedbackData.conversationId - Conversation ID
 * @param {string} [feedbackData.messageId] - Optional message ID
 * @param {number} feedbackData.rating - Rating (1 for thumbs up, -1 for thumbs down)
 * @param {string} [feedbackData.comment] - Optional comment
 * @returns {Promise<Object>} Response with feedback ID
 */
export const submitFeedback = (feedbackData) => request('/api/feedback', { method: 'POST', body: feedbackData });

/**
 * Ask a question and read the answer as it streams in.
 * The server sends newline-delimited JSON: {type: 'delta', text} pieces, then one {type: 'done', ...}
 * with the final text, sources and saved message ids (or `error` / `setup_required`).
 * @param {Object} request
 * @param {string} request.message - The question
 * @param {string|null} request.conversationId - The conversation to continue, or null for a new one
 * @param {(text: string) => void} request.onDelta - Called with each new piece of the answer
 * @param {AbortSignal} [request.signal]
 * @returns {Promise<Object>} The "done" event
 */
export const streamChat = async ({ message, conversationId, onDelta, signal }) => {
  const response = await fetch('/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, conversation_id: conversationId }),
    signal,
  });
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}, message: ${await response.text()}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split('\n');
    buffer = lines.pop(); // an incomplete line waits for the next read
    for (const line of lines.filter((l) => l.trim())) {
      const event = JSON.parse(line);
      if (event.type === 'delta') onDelta(event.text);
      else if (event.type === 'done') return event;
    }
    if (done) throw new Error('The answer stream ended early');
  }
};

/**
 * Whether an AI provider is set up and how much content is indexed
 * @returns {Promise<Object>} {provider_ready, provider_label, model, indexed_chunks}
 */
export const getStatus = () => request('/api/status');

/**
 * Suggestion pills for an empty chat
 * @returns {Promise<Array<{label: string, prompt: string}>>}
 */
export const getSuggestions = () => request('/api/suggestions');

/**
 * The AI providers a key can be added for, and which one is in use
 * @returns {Promise<{provider: string|null, providers: Array<{id, label, has_key, key_url}>}>}
 */
export const getProviders = () => request('/api/settings/llm');

/**
 * Check an API key with its provider, then save it for the whole app and switch the chat to it
 * (the same as Admin → Assistant). Throws with the provider's reason if the key is rejected.
 */
export const saveApiKey = async (provider, apiKey) => {
  await request('/api/settings/llm/models', { method: 'POST', body: { provider, api_key: apiKey } });
  return request('/api/settings/llm', { method: 'PUT', body: { provider, api_key: apiKey } });
};
