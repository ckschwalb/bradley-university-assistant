/**
 * Tests for ChatMessage component feedback functionality
 */

import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import ChatMessage, { withoutSourcesLine } from '../ChatMessage';
import * as api from '../../lib/api';

// Mock the API module
vi.mock('../../lib/api');
const mockSubmitFeedback = api.submitFeedback;

describe('ChatMessage Feedback', () => {
  const mockMessage = {
    id: 'msg-123',
    text: 'This is a test response',
    sender: 'bot',
    timestamp: '10:30 AM',
    sources: []
  };

  const mockConversationId = 'conv-123';

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders feedback buttons for bot messages', () => {
    render(
      <ChatMessage 
        message={mockMessage} 
        conversationId={mockConversationId} 
        isReadOnly={false} 
      />
    );

    expect(screen.getByTitle('This was helpful')).toBeInTheDocument();
    expect(screen.getByTitle('This was not helpful')).toBeInTheDocument();
  });

  it('does not render feedback buttons for user messages', () => {
    const userMessage = { ...mockMessage, sender: 'user' };
    
    render(
      <ChatMessage 
        message={userMessage} 
        conversationId={mockConversationId} 
        isReadOnly={false} 
      />
    );

    expect(screen.queryByTitle('This was helpful')).not.toBeInTheDocument();
    expect(screen.queryByTitle('This was not helpful')).not.toBeInTheDocument();
  });

  it('does not render feedback buttons in read-only mode', () => {
    render(
      <ChatMessage 
        message={mockMessage} 
        conversationId={mockConversationId} 
        isReadOnly={true} 
      />
    );

    expect(screen.queryByTitle('This was helpful')).not.toBeInTheDocument();
    expect(screen.queryByTitle('This was not helpful')).not.toBeInTheDocument();
  });

  it('submits thumbs up feedback successfully', async () => {
    mockSubmitFeedback.mockResolvedValue({ id: 'feedback-123' });

    render(
      <ChatMessage 
        message={mockMessage} 
        conversationId={mockConversationId} 
        isReadOnly={false} 
      />
    );

    const thumbsUpButton = screen.getByTitle('This was helpful');
    fireEvent.click(thumbsUpButton);

    await waitFor(() => {
      expect(mockSubmitFeedback).toHaveBeenCalledWith({
        conversationId: mockConversationId,
        messageId: mockMessage.id,
        rating: 1
      });
    });

    expect(await screen.findByText('Thanks for the feedback!')).toBeInTheDocument();
  });

  it('shows comment box when thumbs down is clicked', () => {
    render(
      <ChatMessage 
        message={mockMessage} 
        conversationId={mockConversationId} 
        isReadOnly={false} 
      />
    );

    const thumbsDownButton = screen.getByTitle('This was not helpful');
    fireEvent.click(thumbsDownButton);

    expect(screen.getByPlaceholderText('Please tell us what we can improve...')).toBeInTheDocument();
    expect(screen.getByText('Submit feedback')).toBeInTheDocument();
    expect(screen.getByText('Cancel')).toBeInTheDocument();
  });

  it('submits thumbs down feedback with comment', async () => {
    mockSubmitFeedback.mockResolvedValue({ id: 'feedback-123' });

    render(
      <ChatMessage 
        message={mockMessage} 
        conversationId={mockConversationId} 
        isReadOnly={false} 
      />
    );

    // Click thumbs down to show comment box
    const thumbsDownButton = screen.getByTitle('This was not helpful');
    fireEvent.click(thumbsDownButton);

    // Type comment
    const commentTextarea = screen.getByPlaceholderText('Please tell us what we can improve...');
    fireEvent.change(commentTextarea, { target: { value: 'This was not helpful' } });

    // Submit feedback
    const submitButton = screen.getByText('Submit feedback');
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(mockSubmitFeedback).toHaveBeenCalledWith({
        conversationId: mockConversationId,
        messageId: mockMessage.id,
        rating: -1,
        comment: 'This was not helpful'
      });
    });

    expect(await screen.findByText("Thanks for the feedback!")).toBeInTheDocument();
  });

  it('cancels comment submission', () => {
    render(
      <ChatMessage 
        message={mockMessage} 
        conversationId={mockConversationId} 
        isReadOnly={false} 
      />
    );

    // Click thumbs down to show comment box
    const thumbsDownButton = screen.getByTitle('This was not helpful');
    fireEvent.click(thumbsDownButton);

    // Type comment
    const commentTextarea = screen.getByPlaceholderText('Please tell us what we can improve...');
    fireEvent.change(commentTextarea, { target: { value: 'This was not helpful' } });

    // Cancel
    const cancelButton = screen.getByText('Cancel');
    fireEvent.click(cancelButton);

    // Comment box should be hidden
    expect(screen.queryByPlaceholderText('Please tell us what we can improve...')).not.toBeInTheDocument();
    expect(screen.queryByText('Submit feedback')).not.toBeInTheDocument();
    expect(screen.queryByText('Cancel')).not.toBeInTheDocument();

    // Feedback buttons should be visible again
    expect(screen.getByTitle('This was helpful')).toBeInTheDocument();
    expect(screen.getByTitle('This was not helpful')).toBeInTheDocument();
  });

  it('disables submit button when comment is empty', () => {
    render(
      <ChatMessage 
        message={mockMessage} 
        conversationId={mockConversationId} 
        isReadOnly={false} 
      />
    );

    // Click thumbs down to show comment box
    const thumbsDownButton = screen.getByTitle('This was not helpful');
    fireEvent.click(thumbsDownButton);

    // Submit button should be disabled
    const submitButton = screen.getByText('Submit feedback');
    expect(submitButton).toBeDisabled();
  });

  it('enables submit button when comment has content', () => {
    render(
      <ChatMessage 
        message={mockMessage} 
        conversationId={mockConversationId} 
        isReadOnly={false} 
      />
    );

    // Click thumbs down to show comment box
    const thumbsDownButton = screen.getByTitle('This was not helpful');
    fireEvent.click(thumbsDownButton);

    // Type comment
    const commentTextarea = screen.getByPlaceholderText('Please tell us what we can improve...');
    fireEvent.change(commentTextarea, { target: { value: 'This was not helpful' } });

    // Submit button should be enabled
    const submitButton = screen.getByText('Submit feedback');
    expect(submitButton).not.toBeDisabled();
  });

  it('replaces the feedback buttons with a thank-you after submission', async () => {
    mockSubmitFeedback.mockResolvedValue({ id: 'feedback-123' });

    render(
      <ChatMessage 
        message={mockMessage} 
        conversationId={mockConversationId} 
        isReadOnly={false} 
      />
    );

    const thumbsUpButton = screen.getByTitle('This was helpful');
    fireEvent.click(thumbsUpButton);

    expect(await screen.findByText('Thanks for the feedback!')).toBeInTheDocument();
    expect(screen.queryByTitle('This was helpful')).not.toBeInTheDocument();
    expect(screen.queryByTitle('This was not helpful')).not.toBeInTheDocument();
  });

  it('handles API errors gracefully', async () => {
    mockSubmitFeedback.mockRejectedValue(new Error('API Error'));

    render(
      <ChatMessage 
        message={mockMessage} 
        conversationId={mockConversationId} 
        isReadOnly={false} 
      />
    );

    const thumbsUpButton = screen.getByTitle('This was helpful');
    fireEvent.click(thumbsUpButton);

    await waitFor(() => {
      expect(mockSubmitFeedback).toHaveBeenCalled();
    });

    // Should not show thank you message on error
    expect(screen.queryByText('Thanks for the feedback!')).not.toBeInTheDocument();
    
    // Buttons should be enabled again after error
    expect(thumbsUpButton).not.toHaveClass('disabled');
  });
});

describe('ChatMessage sources', () => {
  const answer = 'Students live on campus for two years.\n\nSources: [College Search FAQs](https://www.bradley.edu/college-faq/)';

  it('shows the sources bar and hides the assistant\'s own Sources line', () => {
    render(<ChatMessage message={{ id: 'm1', sender: 'bot', text: answer, timestamp: '', noFeedback: true,
      sources: [{ title: 'College Search FAQs', url: 'https://www.bradley.edu/college-faq/' }] }} />);
    expect(screen.getAllByText('College Search FAQs')).toHaveLength(1); // the bar, not also the text line
    expect(screen.getByText(/Students live on campus/)).toBeInTheDocument();
  });

  it('links each source to the page on bradley.edu in a new tab', () => {
    render(<ChatMessage message={{ id: 'm1', sender: 'bot', text: 'Answer.', timestamp: '', noFeedback: true,
      sources: [{ title: 'College Search FAQs', url: 'https://www.bradley.edu/college-faq/' },
                { title: 'CS 100 - Intro', url: 'https://catalog.bradley.edu/cs/#CS_100' }] }} />);
    const faq = screen.getByRole('link', { name: 'College Search FAQs' });
    expect(faq).toHaveAttribute('href', 'https://www.bradley.edu/college-faq/');
    expect(faq).toHaveAttribute('target', '_blank');
    expect(faq).toHaveAttribute('rel', expect.stringContaining('noopener'));
    expect(screen.getByRole('link', { name: 'CS 100 - Intro' })).toHaveAttribute('href', 'https://catalog.bradley.edu/cs/#CS_100');
  });

  it('keeps the assistant\'s Sources line when there is no bar to replace it', () => {
    render(<ChatMessage message={{ id: 'm1', sender: 'bot', text: answer, timestamp: '', noFeedback: true, sources: [] }} />);
    expect(screen.getByText('College Search FAQs')).toBeInTheDocument();
  });

  it('only removes a trailing Sources line', () => {
    expect(withoutSourcesLine(answer)).toBe('Students live on campus for two years.');
    expect(withoutSourcesLine('**Sources:** [A](u), [B](v)')).toBe('**Sources:** [A](u), [B](v)'); // nothing before it
    expect(withoutSourcesLine('Our sources: many.\n\nMore text here.')).toContain('More text here.');
  });
});
