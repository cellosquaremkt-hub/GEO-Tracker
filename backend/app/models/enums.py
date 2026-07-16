import enum


class Target(enum.StrEnum):
    C_LEVEL = "c-level"
    MANAGER = "manager"
    PRACTITIONER = "practitioner"
    JUNIOR = "junior"
    SELLER = "seller"


class Priority(enum.StrEnum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class Language(enum.StrEnum):
    KO = "ko"
    EN = "en"


class ExecutionStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class Sentiment(enum.StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
