import asyncio
import math
from typing import Any

try:
    from ib_insync import IB, LimitOrder, MarketOrder, Stock, StopOrder
except Exception:  # pragma: no cover - handled at runtime if dependency missing
    IB = None
    MarketOrder = None
    LimitOrder = None
    StopOrder = None
    Stock = None


class IBService:
    def __init__(self) -> None:
        self._ib = IB() if IB is not None else None
        self._tickers: dict[str, Any] = {}

    @property
    def available(self) -> bool:
        return self._ib is not None

    @property
    def connected(self) -> bool:
        return bool(self._ib and self._ib.isConnected())

    async def connect(self, host: str, port: int, client_id: int) -> None:
        if not self.available:
            raise RuntimeError("ib-insync is not installed")

        if self.connected:
            self._ib.disconnect()
            self._tickers.clear()

        await self._ib.connectAsync(host, port, clientId=client_id, timeout=6)

    def disconnect(self) -> None:
        if self._ib and self._ib.isConnected():
            for ticker in self._tickers.values():
                self._ib.cancelMktData(ticker.contract)
            self._tickers.clear()
            self._ib.disconnect()

    async def subscribe_symbol(self, symbol: str) -> None:
        if not self.connected:
            return

        symbol = symbol.upper().strip()
        if symbol in self._tickers:
            return

        contract = Stock(symbol, "SMART", "USD")
        qualified = await self._ib.qualifyContractsAsync(contract)
        if not qualified:
            raise ValueError(f"Unable to qualify symbol: {symbol}")

        ticker = self._ib.reqMktData(qualified[0], "", False, False)
        self._tickers[symbol] = ticker

    def _safe_price(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            casted = float(value)
        except (TypeError, ValueError):
            return None

        if math.isnan(casted) or casted <= 0:
            return None

        return round(casted, 4)

    def get_market_snapshot(self, symbols: set[str]) -> list[dict[str, Any]]:
        data: list[dict[str, Any]] = []
        if not self.connected:
            return data

        for symbol in sorted(symbols):
            ticker = self._tickers.get(symbol)
            if ticker is None:
                continue

            price = self._safe_price(ticker.marketPrice())
            if price is None:
                for candidate in (ticker.last, ticker.close, ticker.bid, ticker.ask):
                    price = self._safe_price(candidate)
                    if price is not None:
                        break

            if price is None:
                continue

            data.append({"symbol": symbol, "price": price})

        return data

    async def _qualify(self, symbol: str) -> Any:
        if not self.connected:
            raise RuntimeError("IB is not connected")

        contract = Stock(symbol.upper().strip(), "SMART", "USD")
        qualified = await self._ib.qualifyContractsAsync(contract)
        if not qualified:
            raise ValueError(f"Unable to qualify symbol: {symbol}")

        return qualified[0]

    async def place_market_order(self, symbol: str, side: str, quantity: float) -> dict[str, Any]:
        contract = await self._qualify(symbol)
        order = MarketOrder(side.upper(), quantity)
        trade = self._ib.placeOrder(contract, order)
        await asyncio.sleep(0.4)

        return {
            "symbol": symbol.upper().strip(),
            "side": side.upper(),
            "quantity": quantity,
            "order_type": "MARKET",
            "order_id": trade.order.orderId,
            "status": trade.orderStatus.status,
        }

    async def place_limit_order(self, symbol: str, side: str, quantity: float, limit_price: float) -> dict[str, Any]:
        contract = await self._qualify(symbol)
        order = LimitOrder(side.upper(), quantity, limit_price)
        trade = self._ib.placeOrder(contract, order)
        await asyncio.sleep(0.4)

        return {
            "symbol": symbol.upper().strip(),
            "side": side.upper(),
            "quantity": quantity,
            "order_type": "LIMIT",
            "limit_price": limit_price,
            "order_id": trade.order.orderId,
            "status": trade.orderStatus.status,
        }

    async def place_stop_order(self, symbol: str, side: str, quantity: float, stop_price: float) -> dict[str, Any]:
        contract = await self._qualify(symbol)
        order = StopOrder(side.upper(), quantity, stop_price)
        trade = self._ib.placeOrder(contract, order)
        await asyncio.sleep(0.4)

        return {
            "symbol": symbol.upper().strip(),
            "side": side.upper(),
            "quantity": quantity,
            "order_type": "STOP",
            "stop_price": stop_price,
            "order_id": trade.order.orderId,
            "status": trade.orderStatus.status,
        }
