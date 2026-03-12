const sourceBadge = document.getElementById("sourceBadge");
const ibStatus = document.getElementById("ibStatus");
const quotesTable = document.getElementById("quotesTable");
const activeSymbolSelect = document.getElementById("activeSymbol");
const orderStatus = document.getElementById("orderStatus");

const state = {
  quotes: new Map(),
  baselines: new Map(),
  history: new Map(),
  activeSymbol: "AAPL",
  socket: null,
};

const chart = LightweightCharts.createChart(document.getElementById("chart"), {
  width: document.getElementById("chart").clientWidth,
  height: document.getElementById("chart").clientHeight,
  layout: {
    background: { color: "#081e2f" },
    textColor: "#d7e5f6",
  },
  grid: {
    vertLines: { color: "rgba(255,255,255,0.06)" },
    horzLines: { color: "rgba(255,255,255,0.06)" },
  },
  crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
  rightPriceScale: { borderColor: "rgba(255,255,255,0.15)" },
  timeScale: { borderColor: "rgba(255,255,255,0.15)", timeVisible: true, secondsVisible: true },
});

const series = chart.addLineSeries({
  color: "#0ec9a3",
  lineWidth: 2,
  priceLineColor: "#ff9f43",
  lastValueVisible: true,
});

window.addEventListener("resize", () => {
  const chartEl = document.getElementById("chart");
  chart.applyOptions({ width: chartEl.clientWidth, height: chartEl.clientHeight });
});

function upsertHistory(symbol, price, tsSeconds) {
  const list = state.history.get(symbol) || [];
  list.push({ time: Math.floor(tsSeconds), value: price });
  if (list.length > 1500) {
    list.shift();
  }
  state.history.set(symbol, list);
}

function redrawChart() {
  const points = state.history.get(state.activeSymbol) || [];
  series.setData(points);
}

function setActiveSymbol(symbol) {
  state.activeSymbol = symbol;
  activeSymbolSelect.value = symbol;
  redrawChart();
}

function refreshSymbolSelect() {
  const symbols = [...state.quotes.keys()].sort();
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
  const symbol = tick.symbol;
  const price = Number(tick.price);
  const ts = Number(tick.timestamp || Date.now() / 1000);

  if (!state.baselines.has(symbol)) {
    state.baselines.set(symbol, price);
  }

  state.quotes.set(symbol, price);
  upsertHistory(symbol, price, ts);

  if (symbol === state.activeSymbol) {
    redrawChart();
  }
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
    ibStatus.textContent = `Status: ${flags} | ${capability}`;

    if (Array.isArray(status.tracked_symbols) && status.tracked_symbols.length > 0) {
      await api("/api/market/subscribe", "POST", { symbols: status.tracked_symbols });
    }
  } catch (error) {
    ibStatus.textContent = `Status error: ${error.message}`;
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
    if (message.type !== "ticks" || !Array.isArray(message.data)) return;

    sourceBadge.textContent = `Source: ${message.source || "SIMULATED"}`;

    message.data.forEach((tick) => upsertTick(tick));
    renderTable();
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

activeSymbolSelect.addEventListener("change", (event) => {
  setActiveSymbol(event.target.value);
});

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

  if (symbols.length === 0) {
    return;
  }

  try {
    await api("/api/market/subscribe", "POST", { symbols });
    document.getElementById("symbolsInput").value = "";
  } catch (error) {
    orderStatus.textContent = `Subscription failed: ${error.message}`;
  }
});

document.getElementById("sendOrderBtn").addEventListener("click", async () => {
  try {
    const symbol = document.getElementById("orderSymbol").value.trim().toUpperCase();
    const side = document.getElementById("orderSide").value;
    const quantity = Number(document.getElementById("orderQty").value);

    if (!symbol || quantity <= 0) {
      orderStatus.textContent = "Provide valid symbol and quantity.";
      return;
    }

    const result = await api("/api/orders/market", "POST", { symbol, side, quantity });
    orderStatus.textContent = `Order sent: #${result.order_id} (${result.status})`;
  } catch (error) {
    orderStatus.textContent = `Order failed: ${error.message}`;
  }
});

loadStatus();
connectSocket();
