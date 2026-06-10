# 03 策略路由 Agent 操作草稿

## 角色定位

策略路由 Agent 只負責判斷這檔股票要交給哪個策略模組處理，不負責買賣。

它參照既有 SOP 與舊版 `RuleConstrainedAgent` 的分層結果，但只做路由：

- `long_hold`：交給長期 / 波段持有 Agent。
- `intraday`：交給盤中切入 Agent。這是盤中切入觀察，不代表當沖。
- `day_trade`：交給當沖 Agent。只有標的可當沖、策略允許當沖、盤中條件也適合當沖時才可使用。
- `watch`：保留觀察，等待資料或訊號補齊。
- `reject`：排除，不交給後續策略模組。

## 參照來源

只擷取與路由有關的資訊：

- 加權指數 Agent 的 `operation_mode`：`aggressive / normal / cautious / risk_off`。
- Candidate Scanner 的 `action`：`primary / secondary / reject`。
- 舊版 `RuleConstrainedAgent` 的 `tier`：`primary_review / secondary_watchlist / lower_priority`。
- SOP 的日 K / 週 K / 月 K 共振、月 K 3MA、5K 節奏、60K MACD、量能與籌碼條件。
- 目前是否已有持股。

不擷取：

- 現價買進。
- 加碼、減碼、停損、停利。
- 下單股數與資金配置。
- 個股情境劇本。

## 輸入資料

- Candidate Scanner 結果
- 加權指數 Agent 結果
- 舊 Agent 分層結果，如有
- 個股日 K / 週 K / 月 K
- 個股 5K / 15K / 60K 是否存在
- 60K MACD 是否可判斷
- 是否開放當沖
- 目前策略是否允許當沖
- 目前是否持股
- 量能資料
- 籌碼與法人資料

## 輸出格式

```json
{
  "agent_name": "strategy_router",
  "symbol": "6141",
  "action": "long_hold / intraday / day_trade / watch / reject",
  "reason": ""
}
```

## 路由優先順序

請依序判斷，不要跳步驟：

1. 先處理硬性排除條件，符合就 `reject`。
2. 若已有持股且仍需要持股管理，優先路由到 `long_hold`，交由 Long Swing Agent 處理。
3. 再判斷是否符合長期 / 波段結構，符合才 `long_hold`。
4. 若標的可當沖、策略允許當沖，且盤中條件符合當沖 SOP，才 `day_trade`。
5. 若不符合當沖條件，但只缺盤中切入確認，且資料足夠，才 `intraday`。
6. 條件不足但尚未破壞，給 `watch`。

## 舊 Agent 分層對應

- `primary_review`：可進一步判斷 `long_hold`、`intraday` 或 `day_trade`。
- `secondary_watchlist`：預設 `watch`，不得直接升成操作路由。
- `lower_priority`：預設 `reject`；若仍有結構但只是資料不足，才可保留 `watch`。
- 舊 Agent `decision = reject`：直接 `reject`。
- 舊 Agent `decision = hold`：預設 `watch`。
- 舊 Agent `decision = accept`：只代表可進一步路由，不代表可進場。

## 操作草稿

`reject`：

- Candidate Scanner 已 `reject`。
- 舊 Agent `decision = reject`。
- 舊 Agent `tier = lower_priority`，且沒有明確日週月結構。
- 加權指數 `operation_mode = risk_off`，且個股沒有既有持股管理需求。
- 個股是弱勢股、空頭股、跌破重要均線或無量股。
- 每日成交量低於 500 張，且沒有既有持股管理需求。
- 個股跌破月 K 3MA、均線空頭排列、爆量長黑破壞結構、量縮無趨勢、主流退潮、法人連續偏空或籌碼鬆動。

`watch`：

- Candidate Scanner = `secondary`。
- 舊 Agent `tier = secondary_watchlist`。
- 舊 Agent `decision = hold`。
- 股票有型態或結構，但還缺 5K / 60K / 量價 / 籌碼確認。

`day_trade`：

- 標的明確開放當沖。
- 當前策略明確允許當沖。
- 盤中 5K / 15K / 60K / VWAP / 60K MACD 同步支持。
- 停損與出場條件可以在當日完成。
- 若任一條不成立，不能交給當沖 Agent，只能走 `intraday` 盤中切入觀察或 `watch`。
- 籌碼或法人資料不足，不能列入最積極路由。
- 加權指數 `operation_mode = cautious`，原本可做的訊號先降級觀察。
- 個股位置太高，不適合追價，只能等待回測或盤中確認。
- 入選名單股票只通過週選股條件，但尚未補上操作組規則。
- 從操作組或入選名單降級的股票，先保留觀察一週；一週後仍未轉強再淘汰。

`long_hold`：

- 目前已有持股，且尚未觸發排除條件時，優先路由到 `long_hold`，交由 Long Swing Agent 處理。
- Candidate Scanner = `primary`，或舊 Agent `tier = primary_review`。
- 日 K、週 K、月 K 結構一致，符合多週期共振。
- 日線至少維持 3MA > 8MA > 21MA，且短均斜率向上。
- 週 K 趨勢延續。
- 月 K 趨勢向上，且股價未跌破月 K 3MA。
- 型態明確，例如突破、W、N 字、平台收復、均線開花。
- 量能與籌碼不是負向；若籌碼未確認，只能降為 `watch`。
- 加權指數不可為 `risk_off`；若為 `cautious`，沒有既有持股時優先降為 `watch`。

`intraday`：

- Candidate Scanner = `primary`，或舊 Agent `tier = primary_review`。
- 個股已有初篩資格，但長期 / 波段條件尚未完整到可以交給 `long_hold`。
- 有完整盤中資料：5K、15K、60K。
- 60K MACD 可判斷，且沒有明確轉弱。
- 5K 節奏需要交給 Intraday Agent 判斷，例如開盤紅 K、爆量後回測、連黑後回測支撐。
- 適合等待盤中切入確認，而不是直接判斷長期持有。
- 加權指數不可為 `risk_off`。
- 不可因為股價漲很多就路由到 `intraday`；位置過高但結構仍在時，應先 `watch`。

## 分界原則

`long_hold` 與 `watch` 的分界：

- 日週月共振完整、月 K 3MA 未破、籌碼不負向，才可 `long_hold`。
- 結構有潛力但缺籌碼、量能、週月確認或大盤偏保守，先 `watch`。

`intraday` 與 `watch` 的分界：

- 有 5K / 15K / 60K 與 60K MACD，且個股已通過初篩，才可 `intraday`。
- 缺任一關鍵盤中資料，先 `watch`。

`intraday` 與 `long_hold` 的分界：

- 多週期共振完整、偏持股或波段管理，走 `long_hold`。
- 只有盤中切入待確認、尚未形成長期 / 波段持有依據，走 `intraday`。

## 禁止事項

- 不直接輸出 `enter`。
- 不判斷下單股數。
- 不處理加碼、減碼、停損、停利。
- 不把 `reject` 股票硬轉成 `intraday`。
- 不覆蓋加權指數 `risk_off`。
- 不把入選名單自動當成操作組。
- 不因單一型態就路由到積極策略。

## 可先放進 config 的暫定規則

```yaml
strategy_router:
  symbol_routes:
    "6141": long_hold
    "3481": long_hold
  allow_intraday_default: false
```
