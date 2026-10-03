import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import ChatbotWidget from '../ChatbotWidget';
import * as api from '../../lib/api';

vi.mock('../../lib/api');

const SUGGESTIONS = [
  { label: 'Admissions', prompt: 'What are the admission requirements for first-year students?' },
  { label: 'Campus resources', prompt: 'What campus resources are available to students?' },
];

// The widget starts open on the start screen
const openChat = async () => {
  render(<ChatbotWidget />);
  fireEvent.click(await screen.findByRole('button', { name: 'Start chatting' }));
  await screen.findByPlaceholderText('Type your message...');
};

// streamChat stand-in: sends the pieces through onDelta, then resolves with the final event
const streams = (pieces, done) => async ({ onDelta }) => {
  await new Promise((resolve) => setTimeout(resolve, 0)); // the network: the question renders first
  for (const piece of pieces) {
    onDelta(piece);
    await Promise.resolve();
  }
  return { sources: [], conversation_id: 'c1', user_message_id: 'u1', assistant_message_id: 'a1', ...done };
};

const ask = (text) => {
  fireEvent.change(screen.getByPlaceholderText('Type your message...'), { target: { value: text } });
  fireEvent.click(screen.getByLabelText('Send message'));
};

describe('ChatbotWidget', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getStatus.mockResolvedValue({
      provider_ready: true, demo_mode: false, provider_label: 'Claude (Anthropic)', model: 'claude-haiku', indexed_chunks: 10,
    });
    api.getSuggestions.mockResolvedValue(SUGGESTIONS);
  });

  it('stops the question at the 1000-character limit and shows a count when it is close', async () => {
    await openChat();
    const input = screen.getByPlaceholderText('Type your message...');
    expect(input).toHaveAttribute('maxLength', '1000');
    expect(screen.queryByText(/\/ 1000/)).not.toBeInTheDocument();
    fireEvent.change(input, { target: { value: 'x'.repeat(850) } });
    expect(screen.getByText('850 / 1000')).toBeInTheDocument();
  });

  it('starts open at the default size', async () => {
    await openChat();
    expect(document.querySelector('.chatbot-container')).toBeInTheDocument();
    expect(document.querySelector('.chatbot-container.expanded')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Open Bradley AI Assistant')).not.toBeInTheDocument();
  });

  it('starts as just the launch button on a phone-sized screen', () => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: true }));
    render(<ChatbotWidget />);
    expect(screen.getByLabelText('Open Bradley AI Assistant')).toBeInTheDocument();
    expect(document.querySelector('.chatbot-container')).not.toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it('minimizes to the launch button and reopens with the conversation intact', async () => {
    await openChat();
    fireEvent.click(screen.getByLabelText('Minimize chat'));
    expect(document.querySelector('.chatbot-container')).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Open Bradley AI Assistant'));
    expect(await screen.findByPlaceholderText('Type your message...')).toBeInTheDocument();
  });

  it('enlarges and shrinks the window with the expand button', async () => {
    await openChat();
    fireEvent.click(screen.getByLabelText('Enlarge chat window'));
    expect(document.querySelector('.chatbot-container.expanded')).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Shrink chat window'));
    expect(document.querySelector('.chatbot-container.expanded')).not.toBeInTheDocument();
  });

  it('presents a working prototype, then keeps a one-line notice above the chat', async () => {
    render(<ChatbotWidget />);
    expect(screen.getByText(/A working prototype developed in collaboration with Bradley University. Not officially launched./)).toBeInTheDocument();
    expect(screen.queryByText(/not affiliated|not endorsed/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole('button', { name: 'Start chatting' }));
    await screen.findByPlaceholderText('Type your message...');
    expect(screen.getByText('University-sponsored, not live')).toBeInTheDocument();
    expect(screen.queryByLabelText('Share conversation')).not.toBeInTheDocument();
  });

  it('links to the admin center from the title bar, before and after starting', async () => {
    render(<ChatbotWidget />);
    expect(screen.getByRole('link', { name: /Admin/ })).toHaveAttribute('href', '/admin');
    fireEvent.click(await screen.findByRole('button', { name: 'Start chatting' }));
    await screen.findByPlaceholderText('Type your message...');
    expect(screen.getByRole('link', { name: /Admin/ })).toHaveAttribute('href', '/admin');
  });

  describe('demo mode', () => {
    beforeEach(() => {
      api.getStatus.mockResolvedValue({ provider_ready: false, demo_mode: true, provider_label: null, indexed_chunks: 10 });
      api.getProviders.mockResolvedValue({
        provider: null,
        providers: [
          { id: 'anthropic', label: 'Claude (Anthropic)', key_url: 'https://console.anthropic.com/settings/keys' },
          { id: 'openai', label: 'OpenAI', key_url: 'https://platform.openai.com/api-keys' },
        ],
      });
    });

    it('starts in demo mode without a key, marked in the title bar', async () => {
      render(<ChatbotWidget />);
      fireEvent.click(await screen.findByRole('button', { name: 'Try the demo' }));
      await screen.findByPlaceholderText('Type your message...');
      expect(screen.getByRole('button', { name: 'Demo' })).toBeInTheDocument();
      expect(screen.queryByText(/No AI provider is set up/)).not.toBeInTheDocument();
    });

    it('lets the user add their own key from the start screen, then chats with it', async () => {
      api.saveApiKey.mockResolvedValue({});
      render(<ChatbotWidget />);
      fireEvent.click(await screen.findByRole('button', { name: 'Add your own API key' }));
      fireEvent.change(await screen.findByLabelText('AI provider'), { target: { value: 'openai' } });
      expect(await screen.findByRole('link', { name: /Get a key/ })).toHaveAttribute('href', 'https://platform.openai.com/api-keys');
      fireEvent.change(screen.getByLabelText('API key'), { target: { value: ' sk-test ' } });
      api.getStatus.mockResolvedValue({ provider_ready: true, demo_mode: false, provider_label: 'OpenAI', indexed_chunks: 10 });
      fireEvent.click(screen.getByRole('button', { name: 'Save and start' }));
      await screen.findByPlaceholderText('Type your message...');
      expect(api.saveApiKey).toHaveBeenCalledWith('openai', 'sk-test');
      await waitFor(() => expect(screen.queryByRole('button', { name: 'Demo' })).not.toBeInTheDocument());
    });

    it('shows why a key was rejected and stays on the form', async () => {
      api.saveApiKey.mockRejectedValue(new Error('The API key was rejected'));
      render(<ChatbotWidget />);
      fireEvent.click(await screen.findByRole('button', { name: 'Add your own API key' }));
      fireEvent.change(await screen.findByLabelText('API key'), { target: { value: 'bad' } });
      fireEvent.click(screen.getByRole('button', { name: 'Save and start' }));
      expect(await screen.findByRole('alert')).toHaveTextContent('The API key was rejected');
      expect(screen.queryByPlaceholderText('Type your message...')).not.toBeInTheDocument();
    });

    it('reopens the key form from the Demo chip during a chat', async () => {
      render(<ChatbotWidget />);
      fireEvent.click(await screen.findByRole('button', { name: 'Try the demo' }));
      fireEvent.click(await screen.findByRole('button', { name: 'Demo' }));
      expect(await screen.findByText('Use your own API key')).toBeInTheDocument();
    });
  });

  it('shows the answer as it streams in, then the final text with feedback buttons', async () => {
    let finish;
    api.streamChat.mockImplementation(({ onDelta }) => {
      onDelta('Nursing is ');
      return new Promise((resolve) => { finish = resolve; });
    });
    await openChat();
    ask('Where is nursing?');
    expect(await screen.findByText('Nursing is')).toBeInTheDocument();
    expect(screen.queryByTitle('This was helpful')).not.toBeInTheDocument(); // not while it's still being written
    expect(screen.getByPlaceholderText('Type your message...')).toBeDisabled();
    expect(screen.queryByRole('status', { name: 'The assistant is answering' })).not.toBeInTheDocument(); // words replace the dots
    finish({ response: 'Nursing is in Peoria.', sources: [], conversation_id: 'c1', user_message_id: 'u1', assistant_message_id: 'a1' });
    expect(await screen.findByText('Nursing is in Peoria.')).toBeInTheDocument();
    expect(screen.getByTitle('This was helpful')).toBeInTheDocument();
    expect(api.streamChat.mock.calls[0][0]).toMatchObject({ message: 'Where is nursing?', conversationId: null });
  });

  it('shows the waiting dots on their own, not in a chat bubble', async () => {
    api.streamChat.mockReturnValue(new Promise(() => {}));
    await openChat();
    ask('Where is nursing?');
    const dots = await screen.findByRole('status', { name: 'The assistant is answering' });
    expect(dots.closest('.message-content')).toBeNull();
    expect(dots.closest('.message')).toBeNull();
  });

  it('continues the same conversation on the next question', async () => {
    api.streamChat.mockImplementation(streams(['Hi'], { response: 'Hi' }));
    await openChat();
    ask('Hello');
    await screen.findByText('Hi');
    ask('Again');
    await waitFor(() => expect(api.streamChat).toHaveBeenCalledTimes(2));
    expect(api.streamChat.mock.calls[1][0].conversationId).toBe('c1');
  });

  it('replaces a half-written answer with an error message when the stream fails', async () => {
    api.streamChat.mockImplementation(async ({ onDelta }) => {
      onDelta('Nursing is ');
      throw new Error('Failed to fetch');
    });
    await openChat();
    ask('Where is nursing?');
    expect(await screen.findByText(/Unable to connect to the server/)).toBeInTheDocument();
    expect(screen.queryByText('Nursing is')).not.toBeInTheDocument();
  });

  it('does not show the active model in the header', async () => {
    await openChat();
    await screen.findByText('Admissions');
    expect(screen.queryByText(/claude-haiku/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Claude \(Anthropic\)/)).not.toBeInTheDocument();
  });

  it('shows the pills in a single row container, labelled with their short names', async () => {
    await openChat();
    const pill = await screen.findByText('Admissions');
    expect(pill.closest('.suggestions-container').children).toHaveLength(2);
  });

  it('puts the full request in the editable text box when a pill is picked', async () => {
    await openChat();
    fireEvent.click(await screen.findByText('Campus resources'));
    const input = screen.getByPlaceholderText('Type your message...');
    expect(input.value).toBe(SUGGESTIONS[1].prompt);
    fireEvent.change(input, { target: { value: `${SUGGESTIONS[1].prompt} For graduate students?` } });
    expect(input.value).toMatch(/For graduate students\?$/);
  });

  it('shows no pills when the suggestions cannot be loaded', async () => {
    api.getSuggestions.mockRejectedValue(new Error('down'));
    await openChat();
    await waitFor(() => expect(api.getSuggestions).toHaveBeenCalled());
    expect(screen.queryByText('Admissions')).not.toBeInTheDocument();
  });

  describe('scrolling', () => {
    let scrollTo;

    beforeEach(() => {
      scrollTo = vi.fn();
      Element.prototype.scrollTo = scrollTo;
      Object.defineProperty(HTMLElement.prototype, 'scrollHeight', { configurable: true, value: 900 });
      Object.defineProperty(HTMLElement.prototype, 'offsetTop', { configurable: true, value: 300 });
      api.streamChat.mockImplementation(streams(['A long ', 'reply'], { response: 'A long reply' }));
    });

    afterEach(() => {
      delete HTMLElement.prototype.scrollHeight;
      delete HTMLElement.prototype.offsetTop;
    });

    it('scrolls to the bottom for your message, then once to the start of the reply as it streams', async () => {
      await openChat();
      ask('Hi');

      await screen.findByText('A long reply');
      const tops = scrollTo.mock.calls.map(([options]) => options.top);
      expect(tops).toContain(900);                 // your message and the typing indicator
      // the reply: the top of its bubble (offsetTop 300) with a 12px gap, not the bottom, and only
      // once, so later pieces and the final text don't pull the reader back
      expect(tops[tops.length - 1]).toBe(288);
      expect(tops.filter((t) => t === 288)).toHaveLength(1);
    });
  });
});
