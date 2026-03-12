import asyncio
import random
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import settings
from .ib_service import IBService
from .models import (
    ConnectRequest,
    LimitOrderRequest,
    MarketOrderRequest,
    RiskConfigRequest,
    StopOrderRequest,
    StrategyConfigRequest,
    SubscribeRequest,
)
from .risk import RiskEngine
from .strategy import StrategyEngine


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for connection in self._connections:
            try:
                await connection.send_json(payload)
            except Exception:
                dead.append(connection)

        for connection in dead:
            self._connections.discard(connection)


class HealthResponse(BaseModel):
    status: str


class OrderExecutionError(RuntimeError):
    pass


app = FastAPI(title=settings.app_name, version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = ConnectionManager()
ib_service = IBService()
risk_engine = RiskEngine()
strategy_engine = StrategyEngine()

tracked_symbols: set[str] = set(settings.default_symbols)
latest_prices: dict[str, float] = {}
simulated_prices: dict[str, float] = {}
candles: dict[str, list[dict[str, Any]]] = {}
strategy_events: list[dict[str, Any]] = []

stream_task: asyncio.Task | None = None
stop_event = asyncio.Event()

CANDLE_SECONDS = 5
MAX_CANDLES_PER_SYMBOL = 1500
MAX_STRATEGY_EVENTS = 40

ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT_DIR / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


def _record_strategy_event(event: dict[str, Any]) -> None:
    strategy_events.append(event)
    if len(strategy_events) > MAX_STRATEGY_EVENTS:
        del strategy_events[0 : len(strategy_events) - MAX_STRATEGY_EVENTS]


def _simulate_ticks(symbols: set[str]) -> list[dict[str, Any]]:
    ticks: list[dict[str, Any]] = []
    now = time.time()

    for symbol in sorted(symbols):
        base = simulated_prices.get(symbol)
        if base is None:
            base = random.uniform(60.0, 350.0)

        # Small random walk to emulate market movement for demo mode.
        drift = random.uniform(-1.1, 1.1)
        next_price = max(1.0, base + drift)
        simulated_prices[symbol] = next_price

        ticks.append({"symbol": symbol, "price": round(next_price, 2), "timestamp": now})

    return ticks


def _upsert_candle(symbol: str, price: float, ts_seconds: float) -> tuple[dict[str, Any], bool]:
    bucket = int(ts_seconds // CANDLE_SECONDS) * CANDLE_SECONDS
    series = candles.setdefault(symbol, [])

    if not series or bucket > int(series[-1]["time"]):
        series.append(
            {
                "time": bucket,
                "open": round(price, 4),
                "high": round(price, 4),
                "low": round(price, 4),
                "close": round(price, 4),
            }
        )
        if len(series) > MAX_CANDLES_PER_SYMBOL:
            del series[0 : len(series) - MAX_CANDLES_PER_SYMBOL]
        return series[-1], True

    last = series[-1]
    last["high"] = round(max(float(last["high"]), price), 4)
    last["low"] = round(min(float(last["low"]), price), 4)
    last["close"] = round(price, 4)
    return last, False


async def _execute_order(
    order_type: str,
    symbol: str,
    side: str,
    quantity: float,
    source: str,
    limit_price: float | None = None,
    stop_price: float | None = None,
    allow_simulated: bool = False,
) -> dict[str, Any]:
    symbol = symbol.upper().strip()
    side = side.upper().strip()
    order_type = order_type.upper().strip()

    if order_type not in {"MARKET", "LIMIT", "STOP"}:
        raise OrderExecutionError(f"Unsupported order type: {order_type}")

    reference_price = latest_prices.get(symbol)
    if reference_price is None:
        if order_type == "LIMIT" and limit_price is not None:
            reference_price = limit_price
        elif order_type == "STOP" and stop_price is not None:
            reference_price = stop_price

    if reference_price is None or reference_price <= 0:
        raise OrderExecutionError(f"No reference price available for {symbol}")

    allowed, reason = risk_engine.can_submit(symbol=symbol, side=side, quantity=quantity, reference_price=reference_price)
    if not allowed:
        raise OrderExecutionError(reason)

    executed_via = "IB"
    assume_filled = order_type == "MARKET"

    if order_type == "MARKET":
        if ib_service.connected and not allow_simulated:
            result = await ib_service.place_market_order(symbol=symbol, side=side, quantity=quantity)
        elif allow_simulated:
            executed_via = "SIMULATED"
            result = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "order_type": "MARKET",
                "order_id": f"SIM-{int(time.time() * 1000)}",
                "status": "SIMULATED_FILLED",
            }
        else:
            raise OrderExecutionError("Connect to IB before sending MARKET orders")

    elif order_type == "LIMIT":
        if ib_service.connected and not allow_simulated:
            result = await ib_service.place_limit_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                limit_price=float(limit_price),
            )
        elif allow_simulated:
            executed_via = "SIMULATED"
            assume_filled = False
            result = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "order_type": "LIMIT",
                "limit_price": float(limit_price),
                "order_id": f"SIM-{int(time.time() * 1000)}",
                "status": "SIMULATED_ACCEPTED",
            }
        else:
            raise OrderExecutionError("Connect to IB before sending LIMIT orders")

    else:
        if ib_service.connected and not allow_simulated:
            result = await ib_service.place_stop_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                stop_price=float(stop_price),
            )
        elif allow_simulated:
            executed_via = "SIMULATED"
            assume_filled = False
            result = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "order_type": "STOP",
                "stop_price": float(stop_price),
                "order_id": f"SIM-{int(time.time() * 1000)}",
                "status": "SIMULATED_ACCEPTED",
            }
        else:
            raise OrderExecutionError("Connect to IB before sending STOP orders")

    if assume_filled:
        risk_engine.record_fill(symbol=symbol, side=side, quantity=quantity, fill_price=reference_price)

    result["execution_source"] = source
    result["executed_via"] = executed_via
    result["reference_price"] = round(reference_price, 4)
    result["risk"] = risk_engine.snapshot()
    return result


async def _run_strategy_for_symbol(symbol: str) -> dict[str, Any] | None:
    series = candles.get(symbol, [])
    if len(series) < 2:
        return None

    # Use only closed candles to avoid over-trading inside the active interval.
    decision = strategy_engine.evaluate(symbol=symbol, candles=series[:-1])
    if not decision:
        return None

    allow_simulated = decision["execution_mode"] == "SIMULATED"

    event = {
        "timestamp": time.time(),
        "symbol": decision["symbol"],
        "side": decision["side"],
        "quantity": decision["quantity"],
        "reason": decision["reason"],
        "short_ma": decision["short_ma"],
        "long_ma": decision["long_ma"],
        "execution_mode": decision["execution_mode"],
    }

    try:
        order_result = await _execute_order(
            order_type="MARKET",
            symbol=decision["symbol"],
            side=decision["side"],
            quantity=decision["quantity"],
            source="STRATEGY",
            allow_simulated=allow_simulated,
        )
        event["status"] = "EXECUTED"
        event["order_id"] = order_result.get("order_id")
        event["executed_via"] = order_result.get("executed_via")
    except Exception as exc:
        event["status"] = "REJECTED"
        event["error"] = str(exc)

    _record_strategy_event(event)
    return event


async def _build_ticks() -> tuple[str, list[dict[str, Any]]]:
    if ib_service.connected:
        ib_ticks = ib_service.get_market_snapshot(tracked_symbols)
        if ib_ticks:
            now = time.time()
            for tick in ib_ticks:
                tick["timestamp"] = now
            return "IB", ib_ticks

    return "SIMULATED", _simulate_ticks(tracked_symbols)


async def _stream_loop() -> None:
    interval = max(200, settings.stream_interval_ms) / 1000

    while not stop_event.is_set():
        source, ticks = await _build_ticks()
        candle_updates: list[dict[str, Any]] = []
        strategy_triggered: list[dict[str, Any]] = []

        for tick in ticks:
            symbol = tick["symbol"]
            price = float(tick["price"])
            ts = float(tick["timestamp"])

            latest_prices[symbol] = price
            updated_candle, new_interval = _upsert_candle(symbol=symbol, price=price, ts_seconds=ts)
            candle_updates.append({"symbol": symbol, **updated_candle})

            if new_interval:
                strategy_event = await _run_strategy_for_symbol(symbol)
                if strategy_event:
                    strategy_triggered.append(strategy_event)

        if ticks:
            await manager.broadcast(
                {
                    "type": "market",
                    "source": source,
                    "ticks": ticks,
                    "candles": candle_updates,
                    "strategy_events": strategy_triggered,
                }
            )

        await asyncio.sleep(interval)


@app.on_event("startup")
async def startup_event() -> None:
    global stream_task
    stop_event.clear()
    stream_task = asyncio.create_task(_stream_loop())


@app.on_event("shutdown")
async def shutdown_event() -> None:
    stop_event.set()
    ib_service.disconnect()

    if stream_task:
        stream_task.cancel()
        with suppress(asyncio.CancelledError):
            await stream_task


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/ib/status")
async def ib_status() -> dict[str, Any]:
    return {
        "available": ib_service.available,
        "connected": ib_service.connected,
        "tracked_symbols": sorted(tracked_symbols),
        "candle_interval_seconds": CANDLE_SECONDS,
    }


@app.post("/api/ib/connect")
async def ib_connect(payload: ConnectRequest) -> dict[str, Any]:
    try:
        await ib_service.connect(payload.host, payload.port, payload.client_id)
        for symbol in sorted(tracked_symbols):
            await ib_service.subscribe_symbol(symbol)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "connected": ib_service.connected,
        "host": payload.host,
        "port": payload.port,
        "client_id": payload.client_id,
    }


@app.post("/api/ib/disconnect")
async def ib_disconnect() -> dict[str, Any]:
    ib_service.disconnect()
    return {"connected": False}


@app.post("/api/market/subscribe")
async def subscribe_market(payload: SubscribeRequest) -> dict[str, Any]:
    cleaned = {symbol.upper().strip() for symbol in payload.symbols if symbol.strip()}
    if not cleaned:
        raise HTTPException(status_code=400, detail="No symbols were provided")

    tracked_symbols.update(cleaned)

    if ib_service.connected:
        for symbol in sorted(cleaned):
            try:
                await ib_service.subscribe_symbol(symbol)
            except Exception:
                continue

    return {"tracked_symbols": sorted(tracked_symbols)}


@app.get("/api/market/symbols")
async def market_symbols() -> dict[str, Any]:
    return {"symbols": sorted(tracked_symbols)}


@app.get("/api/market/candles/{symbol}")
async def market_candles(symbol: str, limit: int = Query(default=300, ge=20, le=2000)) -> dict[str, Any]:
    normalized = symbol.upper().strip()
    series = candles.get(normalized, [])
    return {
        "symbol": normalized,
        "interval_seconds": CANDLE_SECONDS,
        "candles": series[-limit:],
    }


@app.post("/api/orders/market")
async def place_market_order(payload: MarketOrderRequest) -> dict[str, Any]:
    try:
        return await _execute_order(
            order_type="MARKET",
            symbol=payload.symbol,
            side=payload.side,
            quantity=payload.quantity,
            source="MANUAL",
            allow_simulated=False,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/orders/limit")
async def place_limit_order(payload: LimitOrderRequest) -> dict[str, Any]:
    try:
        return await _execute_order(
            order_type="LIMIT",
            symbol=payload.symbol,
            side=payload.side,
            quantity=payload.quantity,
            limit_price=payload.limit_price,
            source="MANUAL",
            allow_simulated=False,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/orders/stop")
async def place_stop_order(payload: StopOrderRequest) -> dict[str, Any]:
    try:
        return await _execute_order(
            order_type="STOP",
            symbol=payload.symbol,
            side=payload.side,
            quantity=payload.quantity,
            stop_price=payload.stop_price,
            source="MANUAL",
            allow_simulated=False,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/risk/status")
async def risk_status() -> dict[str, Any]:
    return risk_engine.snapshot()


@app.post("/api/risk/config")
async def risk_config(payload: RiskConfigRequest) -> dict[str, Any]:
    risk_engine.configure(
        max_position_per_symbol=payload.max_position_per_symbol,
        max_notional_per_order=payload.max_notional_per_order,
        max_daily_loss=payload.max_daily_loss,
    )
    return risk_engine.snapshot()


@app.post("/api/strategy/config")
async def strategy_config(payload: StrategyConfigRequest) -> dict[str, Any]:
    config = strategy_engine.set_config(
        symbol=payload.symbol,
        enabled=payload.enabled,
        short_window=payload.short_window,
        long_window=payload.long_window,
        order_quantity=payload.order_quantity,
        execution_mode=payload.execution_mode,
    )

    tracked_symbols.add(config.symbol)
    if ib_service.connected:
        try:
            await ib_service.subscribe_symbol(config.symbol)
        except Exception:
            pass

    return {
        "config": {
            "symbol": config.symbol,
            "enabled": config.enabled,
            "short_window": config.short_window,
            "long_window": config.long_window,
            "order_quantity": config.order_quantity,
            "execution_mode": config.execution_mode,
        },
        "tracked_symbols": sorted(tracked_symbols),
    }


@app.get("/api/strategy/status")
async def strategy_status() -> dict[str, Any]:
    return {
        "configs": strategy_engine.all_configs(),
        "recent_events": strategy_events[-20:],
    }


@app.websocket("/ws/market")
async def market_socket(websocket: WebSocket) -> None:
    await manager.connect(websocket)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
