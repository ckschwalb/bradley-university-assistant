import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { submitFeedback } from '../lib/api';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faThumbsUp, faThumbsDown } from '@fortawesome/free-regular-svg-icons';

// The assistant ends answers with its own "Sources: [Page](url)" line. When the sources bar below
// is showing (it lists only pages search returned that the answer links to), the line is redundant.
export const withoutSourcesLine = (text) => text.replace(/\n+[ \t]*\**Sources?:?\**[^\n]*\s*$/i, '');

const ChatMessage = ({ message, conversationId, isReadOnly = false, feedback = [] }) => {
  const [feedbackState, setFeedbackState] = useState({
    submitted: false,
    showCommentBox: false,
    comment: '',
    isSubmitting: false,
    thankYouMessage: false,
    selectedRating: null // Track which button was clicked
  });

  // Get feedback for this specific message
  const messageFeedback = feedback.filter(fb => fb.message_id === message.id);
  const hasFeedback = messageFeedback.length > 0;
  const thumbsUpCount = messageFeedback.filter(fb => fb.rating === 1).length;
  const thumbsDownCount = messageFeedback.filter(fb => fb.rating === -1).length;

  const handleThumbsUp = async () => {
    if (feedbackState.submitted || isReadOnly) return;
    
    setFeedbackState(prev => ({ ...prev, isSubmitting: true }));
    
    try {
      await submitFeedback({
        conversationId,
        messageId: message.id,
        rating: 1
      });
      
      setFeedbackState(prev => ({ 
        ...prev, 
        submitted: true, 
        isSubmitting: false,
        thankYouMessage: true,
        selectedRating: 1
      }));
    } catch (error) {
      console.error('Failed to submit feedback:', error);
      setFeedbackState(prev => ({ ...prev, isSubmitting: false }));
    }
  };

  const handleThumbsDown = () => {
    if (feedbackState.submitted || isReadOnly) return;
    setFeedbackState(prev => ({ ...prev, showCommentBox: true }));
  };

  const handleCommentSubmit = async () => {
    if (!feedbackState.comment.trim()) return;
    
    setFeedbackState(prev => ({ ...prev, isSubmitting: true }));
    
    try {
      await submitFeedback({
        conversationId,
        messageId: message.id,
        rating: -1,
        comment: feedbackState.comment
      });
      
      setFeedbackState(prev => ({ 
        ...prev, 
        submitted: true, 
        showCommentBox: false,
        isSubmitting: false,
        thankYouMessage: true,
        selectedRating: -1
      }));
    } catch (error) {
      console.error('Failed to submit feedback:', error);
      setFeedbackState(prev => ({ ...prev, isSubmitting: false }));
    }
  };

  const handleCommentChange = (e) => {
    setFeedbackState(prev => ({ ...prev, comment: e.target.value }));
  };

  const handleCancelComment = () => {
    setFeedbackState(prev => ({ 
      ...prev, 
      showCommentBox: false, 
      comment: '' 
    }));
  };

  return (
    <div className={`message ${message.sender}`}>
      <div className="message-content">
        {message.sender === 'bot' ? (
          <ReactMarkdown>
            {message.sources?.length > 0 ? withoutSourcesLine(message.text || '') : message.text || 'No response received'}
          </ReactMarkdown>
        ) : (
          <div>{message.text}</div>
        )}
        
        {/* Demo answers link each quoted page in the text, so they skip the bar */}
        {!message.demo && message.sources && message.sources.length > 0 && (
          <div className="sources">
            <small>
              Sources: {message.sources.map((source, index) => (
                <span key={index}>
                  {source.url ? (
                    <a 
                      href={source.url} 
                      target="_blank" 
                      rel="noopener noreferrer"
                      className="source-link"
                    >
                      {source.title || source.url}
                    </a>
                  ) : (
                    source.title || 'Unknown Source'
                  )}
                  {index < message.sources.length - 1 && ', '}
                </span>
              ))}
            </small>
          </div>
        )}

        {/* Feedback controls for assistant messages */}
        {message.sender === 'bot' && !message.noFeedback && (
          <div className="feedback-controls">
            {isReadOnly ? (
              // Read-only view: show feedback status
              <div className="feedback-status">
                <div className="feedback-indicators">
                  {thumbsUpCount > 0 && (
                    <span className="feedback-indicator thumbs-up">
                      <FontAwesomeIcon icon={faThumbsUp} /> {thumbsUpCount}
                    </span>
                  )}
                  {thumbsDownCount > 0 && (
                    <span className="feedback-indicator thumbs-down">
                      <FontAwesomeIcon icon={faThumbsDown} /> {thumbsDownCount}
                    </span>
                  )}
                  {!hasFeedback && (
                    <span className="feedback-indicator no-feedback">
                      No feedback yet
                    </span>
                  )}
                </div>
                {messageFeedback.filter(fb => fb.rating === -1 && fb.comment).map((fb, index) => (
                  <div key={index} className="feedback-comment-display">
                    <strong>Feedback:</strong> {fb.comment}
                  </div>
                ))}
              </div>
            ) : (
              // Interactive view: show feedback buttons
              <>
                {feedbackState.thankYouMessage ? (
                  <div className="feedback-thanks">
                    <span className="thanks-text">Thanks for the feedback!</span>
                  </div>
                ) : feedbackState.showCommentBox ? (
                  <div className="feedback-comment-box">
                    <textarea
                      value={feedbackState.comment}
                      onChange={handleCommentChange}
                      placeholder="Please tell us what we can improve..."
                      rows={3}
                      disabled={feedbackState.isSubmitting}
                      className="feedback-textarea"
                    />
                    <div className="feedback-comment-actions">
                      <button
                        onClick={handleCommentSubmit}
                        disabled={!feedbackState.comment.trim() || feedbackState.isSubmitting}
                        className="feedback-submit-btn"
                      >
                        {feedbackState.isSubmitting ? 'Submitting...' : 'Submit feedback'}
                      </button>
                      <button
                        onClick={handleCancelComment}
                        disabled={feedbackState.isSubmitting}
                        className="feedback-cancel-btn"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="feedback-buttons">
                    <button
                      onClick={handleThumbsUp}
                      disabled={feedbackState.submitted || feedbackState.isSubmitting}
                      className={`feedback-btn feedback-btn-up ${feedbackState.submitted ? 'disabled' : ''} ${feedbackState.selectedRating === 1 ? 'active' : ''}`}
                      title="This was helpful"
                    >
                      <FontAwesomeIcon icon={faThumbsUp} />
                    </button>
                    <button
                      onClick={handleThumbsDown}
                      disabled={feedbackState.submitted || feedbackState.isSubmitting}
                      className={`feedback-btn feedback-btn-down ${feedbackState.submitted ? 'disabled' : ''} ${feedbackState.selectedRating === -1 ? 'active' : ''}`}
                      title="This was not helpful"
                    >
                      <FontAwesomeIcon icon={faThumbsDown} />
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>
      <div className="message-timestamp">{message.timestamp}</div>
    </div>
  );
};

export default ChatMessage;

