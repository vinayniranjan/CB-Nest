from pydantic import BaseModel, Field, field_validator


class ChatSessionCreate(BaseModel):
    title: str = Field(min_length=3, max_length=120)


class ChatMessageCreate(BaseModel):
    role: str = Field(min_length=3, max_length=20)
    content: str = Field(min_length=1, max_length=4000)


class AIChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    # Returned by /chat/actions when a high-impact action needs explicit confirmation.
    confirmation_token: str | None = Field(default=None, max_length=4096)

    @field_validator("message")
    @classmethod
    def _strip_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be blank")
        return value
