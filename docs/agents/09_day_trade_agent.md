# 09 當沖 Agent

## 角色定位

當沖 Agent 只處理 `route = day_trade` 的股票。

它不是一般盤中切入觀察，也不是波段建倉。只有同時符合以下條件才可以進入：

- 股票明確開放當沖。
- 當前策略明確允許當沖。
- 當日盤中 5K / 15K / 60K / VWAP / 60K MACD 支持。
- 可以定義當日停損與當日出場規則。

## 與盤中切入 Agent 的差異

盤中切入 Agent：

- 可用在不開放當沖的股票。
- 只判斷盤中買點。
- 買進後仍依不能當沖、3MA / 8MA、隔日持股規則管理。

當沖 Agent：

- 只能用在可當沖股票。
- 必須同時規劃進場、停損、出場。
- 不可把波段持有邏輯拿來當當沖理由。

## 當前狀態

目前 paper trade 主策略仍是「不能當沖」。

因此 Day Trade Agent 預設只做候選標記，不會自動執行交易；除非使用者明確把模擬策略改成允許當沖。

## 輸出格式

```json
{
  "agent_name": "day_trade_agent",
  "symbol": "3057",
  "action": "enter_now / wait_pullback / wait / avoid / skip",
  "entry_price": null,
  "stop_loss": null,
  "exit_rule": "",
  "reason": "",
  "is_day_trade_allowed": false,
  "strategy_allows_day_trade": false
}
```

## 硬規則

- `is_day_trade_allowed = false`：直接 `skip` 或 `avoid`。
- `strategy_allows_day_trade = false`：只能記錄為觀察，不可下當沖決策。
- 無法定義停損：不可進場。
- 無法定義當日出場規則：不可進場。
- 大盤 risk_off：不可進場。

