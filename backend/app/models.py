from pydantic import BaseModel, Field


class ConnectRequest(BaseModel):
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=7497)
    client_id: int = Field(default=28)


class SubscribeRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)


class MarketOrderRequest(BaseModel):
    symbol: str
    side: str = Field(pattern="^(BUY|SELL|buy|sell)$")
    quantity: float = Field(gt=0)
