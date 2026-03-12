from dataclasses import dataclass
from datetime import date


@dataclass
class PositionState:
    quantity: float = 0.0
    avg_price: float = 0.0


class RiskEngine:
    def __init__(
        self,
        max_position_per_symbol: float = 200.0,
        max_notional_per_order: float = 25000.0,
        max_daily_loss: float = 3000.0,
    ) -> None:
        self.max_position_per_symbol = max_position_per_symbol
        self.max_notional_per_order = max_notional_per_order
        self.max_daily_loss = max_daily_loss
        self.realized_pnl = 0.0
        self.positions: dict[str, PositionState] = {}
        self._session_day = date.today().isoformat()

    def _roll_session_if_needed(self) -> None:
        today = date.today().isoformat()
        if today != self._session_day:
            self.realized_pnl = 0.0
            self._session_day = today

    def can_submit(self, symbol: str, side: str, quantity: float, reference_price: float) -> tuple[bool, str]:
        self._roll_session_if_needed()

        symbol = symbol.upper().strip()
        side = side.upper().strip()

        if reference_price <= 0:
            return False, "Reference price must be greater than zero"

        if self.realized_pnl <= -self.max_daily_loss:
            return False, "Daily loss limit reached"

        notional = quantity * reference_price
        if notional > self.max_notional_per_order:
            return False, f"Order notional {notional:.2f} exceeds max {self.max_notional_per_order:.2f}"

        current = self.positions.get(symbol, PositionState())
        projected = current.quantity + (quantity if side == "BUY" else -quantity)
        if abs(projected) > self.max_position_per_symbol:
            return False, f"Projected position {projected:.2f} exceeds max +/-{self.max_position_per_symbol:.2f}"

        return True, "ok"

    def record_fill(self, symbol: str, side: str, quantity: float, fill_price: float) -> None:
        self._roll_session_if_needed()

        symbol = symbol.upper().strip()
        side = side.upper().strip()

        delta_qty = quantity if side == "BUY" else -quantity
        position = self.positions.get(symbol, PositionState())

        old_qty = position.quantity
        old_avg = position.avg_price
        new_qty = old_qty + delta_qty

        if old_qty == 0 or (old_qty > 0 and delta_qty > 0) or (old_qty < 0 and delta_qty < 0):
            if old_qty == 0:
                position.avg_price = fill_price
            else:
                total_abs_qty = abs(old_qty) + abs(delta_qty)
                weighted_value = (abs(old_qty) * old_avg) + (abs(delta_qty) * fill_price)
                position.avg_price = weighted_value / total_abs_qty if total_abs_qty else fill_price
            position.quantity = new_qty
            self.positions[symbol] = position
            return

        close_qty = min(abs(old_qty), abs(delta_qty))
        if old_qty > 0 and delta_qty < 0:
            self.realized_pnl += (fill_price - old_avg) * close_qty
        elif old_qty < 0 and delta_qty > 0:
            self.realized_pnl += (old_avg - fill_price) * close_qty

        position.quantity = new_qty
        if new_qty == 0:
            position.avg_price = 0.0
        elif (old_qty > 0 and new_qty < 0) or (old_qty < 0 and new_qty > 0):
            position.avg_price = fill_price

        self.positions[symbol] = position

    def configure(self, max_position_per_symbol: float, max_notional_per_order: float, max_daily_loss: float) -> None:
        self.max_position_per_symbol = max_position_per_symbol
        self.max_notional_per_order = max_notional_per_order
        self.max_daily_loss = max_daily_loss

    def snapshot(self) -> dict:
        self._roll_session_if_needed()
        used_loss = max(0.0, -self.realized_pnl)
        remaining_loss_capacity = max(0.0, self.max_daily_loss - used_loss)

        positions = {
            symbol: {
                "quantity": round(position.quantity, 4),
                "avg_price": round(position.avg_price, 4),
            }
            for symbol, position in self.positions.items()
            if abs(position.quantity) > 1e-9
        }

        return {
            "session_day": self._session_day,
            "limits": {
                "max_position_per_symbol": self.max_position_per_symbol,
                "max_notional_per_order": self.max_notional_per_order,
                "max_daily_loss": self.max_daily_loss,
            },
            "realized_pnl": round(self.realized_pnl, 2),
            "remaining_loss_capacity": round(remaining_loss_capacity, 2),
            "positions": positions,
        }
