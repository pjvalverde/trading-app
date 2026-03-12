import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "IB Trading App")
    ib_host: str = os.getenv("IB_HOST", "127.0.0.1")
    ib_port: int = _env_int("IB_PORT", 7497)
    ib_client_id: int = _env_int("IB_CLIENT_ID", 28)
    default_symbols_raw: str = os.getenv("DEFAULT_SYMBOLS", "AAPL,MSFT,TSLA")
    stream_interval_ms: int = _env_int("STREAM_INTERVAL_MS", 1000)

    @property
    def default_symbols(self) -> list[str]:
        return [symbol.strip().upper() for symbol in self.default_symbols_raw.split(",") if symbol.strip()]


settings = Settings()
