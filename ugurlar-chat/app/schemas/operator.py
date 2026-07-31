from pydantic import BaseModel
from typing import Optional


class OperatorReplyRequest(BaseModel):
    conversation_uid: str
    message: str
    operator_name: str


class OperatorTypingRequest(BaseModel):
    conversation_uid: str
    operator_name: str


class OperatorCloseRequest(BaseModel):
    conversation_uid: str
