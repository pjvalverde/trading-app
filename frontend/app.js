const sourceBadge = document.getElementById("sourceBadge");
const intervalBadge = document.getElementById("intervalBadge");
const ibStatus = document.getElementById("ibStatus");
const quotesTable = document.getElementById("quotesTable");
const activeSymbolSelect = document.getElementById("activeSymbol");
const orderStatus = document.getElementById("orderStatus");
const strategyStatus = document.getElementById("strategyStatus");
const riskStatus = document.getElementById("riskStatus");

const orderTypeEl = document.getElementById("orderType");
const limitWrap = document.getElementById("limitPriceWrap");
const stopWrap = document.getElementById("stopPriceWrap");

const state = {
  quotes: new Map(),
  baselines: new Map(),
  candles: new Map(),
  activeSymbol: "AAPL",
  socket: null,
  intervalSeconds: 5,
};

const chartEl = document.getElementById("chart");
const chart = LightweightCharts.createChart(chartEl, {
  width: chartEl.clientWidth,
  height: chartEl.clientHeight,
  layout: {
    background: { color: "#081e2f" },
    textColor: "#d7e5f6",
  },
  grid: {
    vertLines: { color: "rgba(255,255,255,0.06)" },
    horzLines: { color: "rgba(255,255,255,0.06)" },
  },
  rightPriceScale: { borderColor: "rgba(255,255,255,0.15)" },
  timeScale: { borderColor: "rgba(255,255,255,0.15)", timeVisible: true, secondsVisible: true },
});

const candleSeries = chart.addCandlestickSeries({
  upColor: "#1ed89f",
  downColor: "#ff6d67",
  borderVisible: false,
  wickUpColor: "#1ed89f",
  wickDownColor: "#ff6d67",
});

window.addEventListener("resize", () => {
  chart.applyOptions({ width: chartEl.clientWidth, height: chartEl.clientHeight });
});

function normalizeCandle(raw) {
  return {
    time: Number(raw.time),
    open: Number(raw.open),
    high: Number(raw.high),
    low: Number(raw.low),
    close: Number(raw.close),
  };
}

function upsertCandle(symbol, raw) {
  const candle = normalizeCandle(raw);
  const list = state.candles.get(symbol) || [];

  if (list.length > 0 && Number(list[list.length - 1].time) === candle.time) {
    list[list.length - 1] = candle;
  } else {
    list.push(candle);
  }

  if (list.length > 2000) {
    list.shift();
  }

  state.candles.set(symbol, list);
}

function redrawChart() {
  const series = state.candles.get(state.activeSymbol) || [];
  candleSeries.setData(series);
  chart.timeScale().fitContent();
}

async function loadCandles(symbol) {
  try {
    const payload = await api(`/api/market/candles/${encodeURIComponent(symbol)}?limit=600`);
    state.intervalSeconds = Number(payload.interval_seconds || state.intervalSeconds);
    intervalBadge.textContent = `Candles: ${state.intervalSeconds}s`;

    const normalized = (payload.candles || []).map(normalizeCandle);
    state.candles.set(symbol, normalized);

    if (symbol === state.activeSymbol) {
      redrawChart();
    }
  } catch (error) {
    orderStatus.textContent = `Candle load failed: ${error.message}`;
  }
}

function setActiveSymbol(symbol) {
  state.activeSymbol = symbol;
  activeSymbolSelect.value = symbol;
  if (!state.candles.has(symbol) || state.candles.get(symbol).length === 0) {
    loadCandles(symbol);
  } else {
    redrawChart();
  }
}

function refreshSymbolSelect() {
  const symbolsSet = new Set([...state.quotes.keys(), ...state.candles.keys()]);
  const symbols = [...symbolsSet].sort();
  const current = state.activeSymbol;

  activeSymbolSelect.innerHTML = "";
  symbols.forEach((symbol) => {
    const option = document.createElement("option");
    option.value = symbol;
    option.textContent = symbol;
    activeSymbolSelect.appendChild(option);
  });

  if (symbols.length > 0) {
    setActiveSymbol(symbols.includes(current) ? current : symbols[0]);
  }
}

function renderTable() {
  const symbols = [...state.quotes.keys()].sort();
  quotesTable.innerHTML = "";

  symbols.forEach((symbol) => {
    const quote = state.quotes.get(symbol);
    const baseline = state.baselines.get(symbol) || quote;
    const delta = quote - baseline;
    const pct = baseline ? (delta / baseline) * 100 : 0;

    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${symbol}</td>
      <td>${quote.toFixed(2)}</td>
      <td class="${delta >= 0 ? "change-up" : "change-down"}">${delta >= 0 ? "+" : ""}${pct.toFixed(2)}%</td>
    `;
    quotesTable.appendChild(tr);
  });

  refreshSymbolSelect();
}

function upsertTick(tick) {
  const symbol = String(tick.symbol || "").toUpperCase();
  const price = Number(tick.price);

  if (!symbol || Number.isNaN(price)) return;

  if (!state.baselines.has(symbol)) {
    state.baselines.set(symbol, price);
  }

  state.quotes.set(symbol, price);
}

function renderRiskSnapshot(snapshot) {
  if (!snapshot || !snapshot.limits) return;

  const limits = snapshot.limits;
  document.getElementById("riskMaxPosition").value = limits.max_position_per_symbol;
  document.getElementById("riskMaxNotional").value = limits.max_notional_per_order;
  document.getElementById("riskMaxLoss").value = limits.max_daily_loss;

  const positionCount = Object.keys(snapshot.positions || {}).length;
  riskStatus.textContent = `PnL: ${snapshot.realized_pnl} | Remaining loss: ${snapshot.remaining_loss_capacity} | Open positions: ${positionCount}`;
}

async function api(path, method = "GET", body = null) {
  const options = { method, headers: { "Content-Type": "application/json" } };
  if (body) options.body = JSON.stringify(body);

  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || "Request failed");
  }
  return payload;
}

async function loadStatus() {
  try {
    const status = await api("/api/ib/status");
    const flags = status.connected ? "Connected" : "Disconnected";
    const capability = status.available ? "ib-insync ready" : "ib-insync missing";
    state.intervalSeconds = Number(status.candle_interval_seconds || state.intervalSeconds);
    ibStatus.textContent = `Status: ${flags} | ${capability}`;
    intervalBadge.textContent = `Candles: ${state.intervalSeconds}s`;

    if (Array.isArray(status.tracked_symbols) && status.tracked_symbols.length > 0) {
      await api("/api/market/subscribe", "POST", { symbols: status.tracked_symbols });
      status.tracked_symbols.forEach((symbol) => {
        if (!state.candles.has(symbol)) {
          state.candles.set(symbol, []);
        }
        loadCandles(symbol);
      });
      refreshSymbolSelect();
    }
  } catch (error) {
    ibStatus.textContent = `Status error: ${error.message}`;
  }
}

async function loadRiskStatus() {
  try {
    const snapshot = await api("/api/risk/status");
    renderRiskSnapshot(snapshot);
  } catch (error) {
    riskStatus.textContent = `Risk status error: ${error.message}`;
  }
}

async function loadStrategyStatus() {
  try {
    const payload = await api("/api/strategy/status");
    const last = (payload.recent_events || []).slice(-1)[0];
    if (last) {
      const marker = last.status === "EXECUTED" ? "EXEC" : "REJ";
      strategyStatus.textContent = `${marker} ${last.symbol} ${last.side} | ${last.reason}`;
    }
  } catch (error) {
    strategyStatus.textContent = `Strategy status error: ${error.message}`;
  }
}

function connectSocket() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws/market`);
  state.socket = socket;

  socket.onopen = () => {
    socket.send("ping");
  };

  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.type !== "market") return;

    sourceBadge.textContent = `Source: ${message.source || "SIMULATED"}`;

    (message.ticks || []).forEach((tick) => upsertTick(tick));
    (message.candles || []).forEach((candle) => {
      const symbol = String(candle.symbol || "").toUpperCase();
      if (!symbol) return;
      upsertCandle(symbol, candle);
    });

    const events = message.strategy_events || [];
    if (events.length > 0) {
      const latest = events[events.length - 1];
      const marker = latest.status === "EXECUTED" ? "EXEC" : "REJ";
      strategyStatus.textContent = `${marker} ${latest.symbol} ${latest.side} | ${latest.reason}`;
    }

    renderTable();
    if (state.activeSymbol) {
      redrawChart();
    }
  };

  socket.onclose = () => {
    setTimeout(connectSocket, 1800);
  };
}

setInterval(() => {
  if (state.socket && state.socket.readyState === WebSocket.OPEN) {
    state.socket.send("ping");
  }
}, 10000);

setInterval(() => {
  loadRiskStatus();
  loadStrategyStatus();
}, 12000);

activeSymbolSelect.addEventListener("change", (event) => {
  setActiveSymbol(event.target.value);
});

orderTypeEl.addEventListener("change", () => {
  const type = orderTypeEl.value;
  limitWrap.classList.toggle("hidden", type !== "LIMIT");
  stopWrap.classList.toggle("hidden", type !== "STOP");
});

orderTypeEl.dispatchEvent(new Event("change"));

document.getElementById("connectBtn").addEventListener("click", async () => {
  try {
    const host = document.getElementById("ibHost").value.trim();
    const port = Number(document.getElementById("ibPort").value);
    const clientId = Number(document.getElementById("ibClientId").value);

    await api("/api/ib/connect", "POST", { host, port, client_id: clientId });
    await loadStatus();
  } catch (error) {
    ibStatus.textContent = `Connect failed: ${error.message}`;
  }
});

document.getElementById("disconnectBtn").addEventListener("click", async () => {
  try {
    await api("/api/ib/disconnect", "POST");
    await loadStatus();
  } catch (error) {
    ibStatus.textContent = `Disconnect failed: ${error.message}`;
  }
});

document.getElementById("subscribeBtn").addEventListener("click", async () => {
  const raw = document.getElementById("symbolsInput").value;
  const symbols = raw
    .split(/[ ,]+/)
    .map((symbol) => symbol.trim().toUpperCase())
    .filter(Boolean);

  if (symbols.length === 0) return;

  try {
    await api("/api/market/subscribe", "POST", { symbols });
    document.getElementById("symbolsInput").value = "";
    symbols.forEach((symbol) => loadCandles(symbol));
  } catch (error) {
    orderStatus.textContent = `Subscription failed: ${error.message}`;
  }
});

document.getElementById("sendOrderBtn").addEventListener("click", async () => {
  try {
    const orderType = orderTypeEl.value;
    const symbol = document.getElementById("orderSymbol").value.trim().toUpperCase() || state.activeSymbol;
    const side = document.getElementById("orderSide").value;
    const quantity = Number(document.getElementById("orderQty").value);

    if (!symbol || quantity <= 0) {
      orderStatus.textContent = "Provide valid symbol and quantity.";
      return;
    }

    let endpoint = "/api/orders/market";
    let payload = { symbol, side, quantity };

    if (orderType === "LIMIT") {
      endpoint = "/api/orders/limit";
      const limitPrice = Number(document.getElementById("limitPrice").value);
      if (!limitPrice || limitPrice <= 0) {
        orderStatus.textContent = "Provide a valid limit price.";
        return;
      }
      payload.limit_price = limitPrice;
    }

    if (orderType === "STOP") {
      endpoint = "/api/orders/stop";
      const stopPrice = Number(document.getElementById("stopPrice").value);
      if (!stopPrice || stopPrice <= 0) {
        orderStatus.textContent = "Provide a valid stop price.";
        return;
      }
      payload.stop_price = stopPrice;
    }

    const result = await api(endpoint, "POST", payload);
    orderStatus.textContent = `Order ${result.order_type} #${result.order_id} (${result.status}) via ${result.executed_via}`;
    renderRiskSnapshot(result.risk);
  } catch (error) {
    orderStatus.textContent = `Order failed: ${error.message}`;
  }
});

document.getElementById("applyStrategyBtn").addEventListener("click", async () => {
  try {
    const symbol = (document.getElementById("strategySymbol").value.trim() || state.activeSymbol).toUpperCase();
    const enabled = document.getElementById("strategyEnabled").value === "true";
    const shortWindow = Number(document.getElementById("strategyShort").value);
    const longWindow = Number(document.getElementById("strategyLong").value);
    const orderQuantity = Number(document.getElementById("strategyQty").value);
    const executionMode = document.getElementById("strategyMode").value;

    const payload = {
      symbol,
      enabled,
      short_window: shortWindow,
      long_window: longWindow,
      order_quantity: orderQuantity,
      execution_mode: executionMode,
    };

    await api("/api/strategy/config", "POST", payload);
    strategyStatus.textContent = `Strategy updated for ${symbol} (${enabled ? "ON" : "OFF"})`;
    await api("/api/market/subscribe", "POST", { symbols: [symbol] });
    await loadCandles(symbol);
  } catch (error) {
    strategyStatus.textContent = `Strategy update failed: ${error.message}`;
  }
});

document.getElementById("applyRiskBtn").addEventListener("click", async () => {
  try {
    const maxPosition = Number(document.getElementById("riskMaxPosition").value);
    const maxNotional = Number(document.getElementById("riskMaxNotional").value);
    const maxDailyLoss = Number(document.getElementById("riskMaxLoss").value);

    const snapshot = await api("/api/risk/config", "POST", {
      max_position_per_symbol: maxPosition,
      max_notional_per_order: maxNotional,
      max_daily_loss: maxDailyLoss,
    });

    renderRiskSnapshot(snapshot);
  } catch (error) {
    riskStatus.textContent = `Risk update failed: ${error.message}`;
  }
});

(async () => {
  await loadStatus();
  await loadRiskStatus();
  await loadStrategyStatus();
  connectSocket();
})();

