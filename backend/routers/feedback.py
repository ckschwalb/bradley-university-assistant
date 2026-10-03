"""
Feedback router: thumbs up/down on an answer, with an optional comment
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from db import get_session
from models import Conversation, Feedback, Message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["feedback"])


class FeedbackRequest(BaseModel):
    conversationId: str
    messageId: Optional[str] = None
    rating: int
    comment: Optional[str] = None


class FeedbackResponse(BaseModel):
    id: str


@router.post("/feedback", response_model=FeedbackResponse)
async def create_feedback(request: FeedbackRequest, session: Session = Depends(get_session)):
    """Record feedback for a conversation, or for one of its messages"""
    if request.rating not in (1, -1):
        raise HTTPException(status_code=400, detail="Rating must be 1 (thumbs up) or -1 (thumbs down)")
    if session.get(Conversation, request.conversationId) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    message_id = None
    if request.messageId:
        message = session.get(Message, request.messageId)
        if message is None or message.conversation_id != request.conversationId:
            raise HTTPException(status_code=404, detail="Message not found in this conversation")
        message_id = message.id

    feedback = Feedback(conversation_id=request.conversationId, message_id=message_id, rating=request.rating,
                        comment=request.comment)
    session.add(feedback)
    session.commit()
    logger.info(f"Feedback {feedback.id}: rating {request.rating} on conversation {request.conversationId}")
    return FeedbackResponse(id=feedback.id)
