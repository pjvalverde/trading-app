param(
  [string]$HostAddress = "0.0.0.0",
  [int]$Port = 8000
)

uvicorn backend.app.main:app --reload --host $HostAddress --port $Port
