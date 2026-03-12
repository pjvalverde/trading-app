from dataclasses import dataclass
from statistics import mean


@dataclass
class StrategyConfig:
    symbol: str
    enabled: bool = False
    short_window: int = 5
    long_window: int = 15
    order_quantity: float = 1.0
    execution_mode: str = "SIMULATED"


class StrategyEngine:
    def __init__(self) -> None:
        self._configs: dict[str, StrategyConfig] = {}
        self._last_signal: dict[str, str] = {}

    def set_config(
        self,
        symbol: str,
        enabled: bool,
        short_window: int,
        long_window: int,
        order_quantity: float,
        execution_mode: str,
    ) -> StrategyConfig:
        normalized_symbol = symbol.upper().strip()
        normalized_mode = execution_mode.upper().strip()

        config = StrategyConfig(
            symbol=normalized_symbol,
            enabled=enabled,
            short_window=short_window,
            long_window=long_window,
            order_quantity=order_quantity,
            execution_mode=normalized_mode,
        )
        self._configs[normalized_symbol] = config
        return config

    def get_config(self, symbol: str) -> StrategyConfig:
        normalized_symbol = symbol.upper().strip()
        return self._configs.get(normalized_symbol, StrategyConfig(symbol=normalized_symbol))

    def all_configs(self) -> list[dict]:
        return [
            {
                "symbol": cfg.symbol,
                "enabled": cfg.enabled,
                "short_window": cfg.short_window,
                "long_window": cfg.long_window,
                "order_quantity": cfg.order_quantity,
                "execution_mode": cfg.execution_mode,
            }
            for cfg in sorted(self._configs.values(), key=lambda item: item.symbol)
        ]

    def evaluate(self, symbol: str, candles: list[dict]) -> dict | None:
        cfg = self.get_config(symbol)
        if not cfg.enabled:
            return None

        if len(candles) < cfg.long_window:
            return None

        closes = [float(candle["close"]) for candle in candles]
        short_ma = mean(closes[-cfg.short_window:])
        long_ma = mean(closes[-cfg.long_window:])

        if short_ma == long_ma:
            return None

        signal = "BUY" if short_ma > long_ma else "SELL"
        if self._last_signal.get(cfg.symbol) == signal:
            return None

        self._last_signal[cfg.symbol] = signal

        return {
            "symbol": cfg.symbol,
            "side": signal,
            "quantity": cfg.order_quantity,
            "execution_mode": cfg.execution_mode,
            "reason": f"SMA crossover ({cfg.short_window}/{cfg.long_window})",
            "short_ma": round(short_ma, 4),
            "long_ma": round(long_ma, 4),
        }
