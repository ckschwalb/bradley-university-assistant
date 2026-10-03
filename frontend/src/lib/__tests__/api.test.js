import { describe, it, expect, vi, afterEach } from 'vitest';
import { streamChat } from '../api';

// A fetch response whose body arrives in the given chunks, split anywhere (even mid-line)
const streamed = (...chunks) => {
  const encoder = new TextEncoder();
  let i = 0;
  return {
    ok: true,
    body: { getReader: () => ({ read: async () => (i < chunks.length ? { value: encoder.encode(chunks[i++]), done: false } : { done: true }) }) },
  };
};

describe('streamChat', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('passes each piece on and returns the final event, however the lines are split', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamed(
      '{"type":"delta","text":"In "}\n{"type":"del',
      'ta","text":"Peoria."}\n',
      '{"type":"done","response":"In Peoria.","sources":[],"assistant_message_id":"a1"}\n',
    )));
    const pieces = [];
    const done = await streamChat({ message: 'Where?', conversationId: null, onDelta: (t) => pieces.push(t) });
    expect(pieces).toEqual(['In ', 'Peoria.']);
    expect(done).toMatchObject({ type: 'done', response: 'In Peoria.', assistant_message_id: 'a1' });
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ message: 'Where?', conversation_id: null });
  });

  it('fails if the stream ends without a final event', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamed('{"type":"delta","text":"In "}\n')));
    await expect(streamChat({ message: 'Where?', conversationId: null, onDelta: () => {} })).rejects.toThrow(/ended early/);
  });
});
