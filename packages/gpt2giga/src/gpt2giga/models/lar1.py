"""LAR-1 semantic metadata models.

LAR-1 adds machine-readable semantics to agent messages:
act, time, mind, confidence, evidence.
"""

from enum import Enum

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LAR1Act(str, Enum):
    INF = "INF"
    OBS = "OBS"
    RET = "RET"
    GEN = "GEN"


class LAR1Time(str, Enum):
    NOW = "NOW"
    MEM = "MEM"
    CTX = "CTX"
    PRE = "PRE"


class LAR1Mind(str, Enum):
    REF = "REF"
    REC = "REC"
    HYP = "HYP"
    ACT = "ACT"


class LAR1Evidence(str, Enum):
    SYNTH = "SYNTH"
    RETRIEVED = "RETRIEVED"
    UNVERIFIED = "UNVERIFIED"
    CONFIRMED = "CONFIRMED"


class LAR1Metadata(BaseModel):
    act: LAR1Act = LAR1Act.INF
    time: LAR1Time = LAR1Time.NOW
    mind: LAR1Mind = LAR1Mind.REF
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence: list[LAR1Evidence] = Field(default_factory=list)


class LAR1Settings(BaseSettings):
    """Environment-backed LAR-1 routing configuration."""

    enabled: bool = Field(
        default=False,
        description="Enable LAR-1 metadata processing and model selection.",
    )
    threshold_low: float = Field(default=0.3, ge=0.0, lt=1.0)
    threshold_medium: float = Field(default=0.5, ge=0.0, lt=1.0)
    threshold_high: float = Field(default=0.7, ge=0.0, lt=1.0)
    model_gigachat_pro: str = Field(
        default="GigaChat-Pro",
        description="Продвинутая модель GigaChat: mid-confidence или time=MEM.",
    )
    model_gigachat_fast: str = Field(
        default="GigaChat",
        description="Экономичная модель GigaChat: low-confidence или UNVERIFIED evidence.",
    )
    model_local: str = Field(
        default="GigaChat",
        description="Экономичная/быстрая модель GigaChat: high-confidence.",
    )

    model_config = SettingsConfigDict(env_prefix="LAR1_", case_sensitive=False)

    @model_validator(mode="after")
    def validate_threshold_order(self) -> "LAR1Settings":
        if not (self.threshold_low < self.threshold_medium < self.threshold_high):
            msg = "LAR-1 thresholds must satisfy low < medium < high"
            raise ValueError(msg)
        return self

    def thresholds(self) -> dict[str, float]:
        return {
            "low": self.threshold_low,
            "medium": self.threshold_medium,
            "high": self.threshold_high,
        }
