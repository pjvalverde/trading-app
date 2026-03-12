import asyncio
import random
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import settings
from .ib_service import IBService
from .models import ConnectRequest, MarketOrderRequest, SubscribeRequest


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


app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = ConnectionManager()
ib_service = IBService()
tracked_symbols: set[str] = set(settings.default_symbols)
simulated_prices: dict[str, float] = {}
stream_task: asyncio.Task | None = None
stop_event = asyncio.Event()

ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT_DIR / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


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


async def _build_ticks() -> tuple[str, list[dict[str, Any]]]:
    if ib_service.connected:
        ib_ticks = ib_service.get_market_snapshot(tracked_symbols)
        for tick in ib_ticks:
            tick["timestamp"] = time.time()
        if ib_ticks:
            return "IB", ib_ticks

    return "SIMULATED", _simulate_ticks(tracked_symbols)


async def _stream_loop() -> None:
    interval = max(200, settings.stream_interval_ms) / 1000
    while not stop_event.is_set():
        source, ticks = await _build_ticks()
        if ticks:
            await manager.broadcast({"type": "ticks", "source": source, "data": ticks})
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
                # Keep streaming for valid symbols if one fails.
                continue

    return {"tracked_symbols": sorted(tracked_symbols)}


@app.get("/api/market/symbols")
async def market_symbols() -> dict[str, Any]:
    return {"symbols": sorted(tracked_symbols)}


@app.post("/api/orders/market")
async def place_market_order(payload: MarketOrderRequest) -> dict[str, Any]:
    if not ib_service.connected:
        raise HTTPException(status_code=400, detail="Connect to IB before sending orders")

    try:
        result = await ib_service.place_market_order(
            symbol=payload.symbol,
            side=payload.side,
            quantity=payload.quantity,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return result


@app.websocket("/ws/market")
async def market_socket(websocket: WebSocket) -> None:
    await manager.connect(websocket)

    try:
        while True:
            # Keep the socket open and allow optional pings from the UI.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
