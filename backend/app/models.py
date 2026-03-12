from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ConnectRequest(BaseModel):
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=7497)
    client_id: int = Field(default=28)


class SubscribeRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)


class MarketOrderRequest(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL", "buy", "sell"]
    quantity: float = Field(gt=0)


class LimitOrderRequest(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL", "buy", "sell"]
    quantity: float = Field(gt=0)
    limit_price: float = Field(gt=0)


class StopOrderRequest(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL", "buy", "sell"]
    quantity: float = Field(gt=0)
    stop_price: float = Field(gt=0)


class StrategyConfigRequest(BaseModel):
    symbol: str
    enabled: bool = True
    short_window: int = Field(default=5, ge=2, le=100)
    long_window: int = Field(default=15, ge=3, le=200)
    order_quantity: float = Field(default=1, gt=0)
    execution_mode: Literal["SIMULATED", "LIVE_IB"] = "SIMULATED"

    @model_validator(mode="after")
    def validate_windows(self) -> "StrategyConfigRequest":
        if self.short_window >= self.long_window:
            raise ValueError("short_window must be lower than long_window")
        return self


class RiskConfigRequest(BaseModel):
    max_position_per_symbol: float = Field(gt=0)
    max_notional_per_order: float = Field(gt=0)
    max_daily_loss: float = Field(gt=0)
