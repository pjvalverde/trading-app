# Trading App (Interactive Brokers + Real-Time UI)

Starter platform for real-time trading with Interactive Brokers (TWS or IB Gateway).

## What is implemented

- FastAPI backend with `ib-insync`
- Real-time tick streaming via WebSocket
- Candlestick aggregation in real time (5-second candles)
- Browser UI with live candlestick chart + watchlist
- Manual order endpoints:
  - MARKET (`/api/orders/market`)
  - LIMIT (`/api/orders/limit`)
  - STOP (`/api/orders/stop`)
- Strategy module (SMA crossover) with toggle and parameters
- Risk module:
  - max position per symbol
  - max order notional
  - max daily realized loss
- Simulated feed when IB is not connected

## Project structure

- `backend/app/main.py`: API, sockets, candle engine, strategy orchestration
- `backend/app/ib_service.py`: IB connection and order routing
- `backend/app/risk.py`: risk limits and PnL/position state
- `backend/app/strategy.py`: SMA strategy engine
- `frontend/index.html`: UI layout
- `frontend/app.js`: frontend logic and API integration
- `frontend/app.css`: styling

## Requirements

- Python 3.10+
- TWS or IB Gateway (for live IB routing)
- Market data permissions in IB for requested symbols

## Quick start

```powershell
cd D:\Apps-2026\Trading-App
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

Open: `http://localhost:8000`

## Interactive Brokers defaults

- TWS paper: `127.0.0.1:7497`
- IB Gateway paper: `127.0.0.1:4002`

## Safety note

Orders sent to IB are real requests for the account/session connected in TWS/Gateway.
Use paper account while testing.

## Next suggested upgrades

- persistent storage (PostgreSQL) for orders/fills/positions
- authentication and per-user permissions
- backtesting and optimization module
- portfolio dashboard and risk exposure by sector
