# Trading App (Interactive Brokers + Real-Time UI)

This project is a real-time trading platform starter that connects to Interactive Brokers (TWS or IB Gateway), streams live prices to a web UI, and lets you send market orders.

## Features

- FastAPI backend with IB integration (`ib-insync`)
- WebSocket streaming for live ticks
- Real-time chart and watchlist in browser
- Market order endpoint (BUY/SELL)
- Simulated price mode when IB is not connected

## Project structure

- `backend/app/main.py`: API, WebSocket, stream loop
- `backend/app/ib_service.py`: Interactive Brokers connection and order placement
- `frontend/index.html`: UI
- `frontend/app.js`: chart, socket, actions
- `frontend/app.css`: styling

## Requirements

- Python 3.10+
- TWS or IB Gateway running locally
- Active IB market data permissions for symbols you request

## Quick start

1. Create and activate virtual environment:

```powershell
cd D:\Apps-2026\Trading-App
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r backend\requirements.txt
```

3. Run backend:

```powershell
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

4. Open in browser:

- `http://localhost:8000`

## Connect to IB

- TWS paper default: host `127.0.0.1`, port `7497`
- IB Gateway paper default: host `127.0.0.1`, port `4002`

Then click **Connect IB** from the UI.

If connection fails, verify:

- TWS/Gateway is running
- API is enabled in TWS/Gateway settings
- Correct port and client ID
- Firewall/network allows local connection

## Order execution note

Orders are real requests to IB once connected. Use paper account first.

## Next upgrades recommended

- Add authenticated users and role-based permissions
- Add persistent order/position storage (PostgreSQL)
- Add risk checks (max position, max daily loss)
- Add stop/limit/bracket orders
- Add strategy module and backtesting
