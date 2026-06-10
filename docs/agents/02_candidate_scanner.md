# 02 股票初篩 Candidate Scanner 操作草稿

## 角色定位

股票初篩負責從全市場或觀察池中留下可研究標的，排除弱勢股、無量股、空頭股。此模組目前保留原本 `RuleConstrainedAgent` 作為股票評分核心。

本 Agent 可以參照原本 `RuleConstrainedAgent.evaluate()` 的評分、分層與排除原因，但只取「候選股初篩」相關資訊，不承接進場、停損、部位管理、當沖切入或最終買賣決策。

目前程式上是由 `CandidateScannerAgent` 包住原本的 `RuleConstrainedAgent`，再把舊分層轉成：

- `primary_review` -> `primary`
- `secondary_watchlist` -> `secondary`
- `lower_priority` 或 `reject` -> `reject`

## 輸入資料

- 個股日 K
- 個股週 K / 月 K
- 3MA / 8MA / 21MA / 55MA / 144MA / 233MA
- 成交量與量比
- 型態偵測結果
- 籌碼資料
- 法人資料
- 加權指數 Agent 結果

資料待補：

- 正式籌碼資料來源
- 法人買賣超資料來源
- 全市場掃描範圍

## 可參照舊 Agent 的資訊

只擷取以下欄位與規則：

- `trend.trend_score`：趨勢結構分數。
- `trend.ma_score`：均線排列分數。
- `trend.market_state`：是否為 `weak_or_unclear`。
- `pattern.score`：型態分數。
- `pattern.pattern_type`：是否有既有允許型態。
- `latest.volume`：日成交量。
- `latest.volume_ratio`：量比。
- `chip_score`：籌碼分數。
- `chip_reason`：籌碼判斷理由。
- `rules.scanner.primary_min_score`：主要候選分數門檻，目前為 75。
- `rules.scanner.secondary_min_score`：次要觀察分數門檻，目前為 55。
- `rules.scanner.min_daily_volume_shares`：最低日成交量，目前為 500,000 股，也就是 500 張。
- `rules.scanner.min_volume_ratio_breakout`：突破量比門檻，目前為 1.2。
- `rules.scanner.allowed_patterns`：允許型態，包含 breakout、w_pattern、n_pattern、platform_reclaim、ma_bloom。

不擷取以下內容：

- 進場價格。
- 停損、停利、減碼、加碼。
- 部位大小。
- 當沖切入點。
- 5K / 60K 的實際進場判斷。
- 最終 `BUY` / `SELL` / `enter_now` 決策。

## 輸出格式

```json
{
  "agent_name": "candidate_scanner",
  "symbol": "6141",
  "action": "primary / secondary / reject",
  "score": 0,
  "reason": "",
  "details": {
    "legacy_decision": "accept / hold / reject",
    "legacy_tier": "primary_review / secondary_watchlist / lower_priority"
  }
}
```

## 操作草稿

`primary`：

- 舊 Agent 分層為 `primary_review`。
- 分數達 `primary_min_score`，目前為 75。
- 均線結構強，日 K 至少維持 3MA > 8MA > 21MA。
- 價格站在主要均線上方。
- 型態明確，且屬於既有允許型態：突破、W、N 字、平台收復、均線開花。
- 日成交量通過最低門檻，且量比不是無量狀態。
- 籌碼分數 `chip_score > 0`，或已有明確偏多理由。

補充限制：

- 若籌碼未確認偏多，即使分數夠高，也不能列為最強操作組，只能降為 `secondary`。
- `primary` 只代表優先研究，不代表可以直接買進。

`secondary`：

- 舊 Agent 分層為 `secondary_watchlist`。
- 分數達 `secondary_min_score`，目前為 55，但未達主要候選條件。
- 結構有潛力，但仍缺確認。
- 可能是回測 3MA / 8MA / 週月交會支撐。
- 量能、型態或籌碼資料不足。
- `chip_score <= 0` 時，不可升為 `primary`，只能列入觀察。
- 只能進觀察或等待下一層 Agent 判斷。

`reject`：

- 舊 Agent 分層為 `lower_priority`，或舊決策已經是 `reject`。
- 沒有可辨識型態結構。
- 大盤或個股趨勢狀態為 `weak_or_unclear`。
- 弱勢或空頭排列。
- 跌破關鍵均線且站不回。
- 日成交量低於 500 張。
- 無量、爆量不漲、型態失敗。
- 缺資料且無法判斷，不可硬列入候選。

## 排除規則

### 弱勢股

符合任一條件，先排除或至少不得列為 `primary`：

- `trend.market_state = weak_or_unclear`。
- 價格跌破重要均線後站不回。
- 趨勢分數與均線分數明顯不足。
- 沒有主流題材、強勢族群、攻擊量、法人偏多或籌碼偏多等既有強勢條件。

### 空頭股

符合任一條件，輸出 `reject`：

- 均線呈空頭排列。
- 價格長時間在短中期均線下方。
- 跌破重要均線且沒有收復跡象。
- 型態偵測沒有給出可用結構。

### 無量股

符合任一條件，輸出 `reject` 或不得列為 `primary`：

- 日成交量低於 `min_daily_volume_shares`，目前為 500,000 股，也就是 500 張。
- 突破情境下量比低於 `min_volume_ratio_breakout`，目前為 1.2。
- 舊 Agent 已標記「沒有足夠成交量，不列最高優先」。

### 強勢股

符合越多條件，越有資格進入 `primary` 或 `secondary`：

- 日 K 至少維持 3MA > 8MA > 21MA。
- 價格站在主要均線上方。
- 型態屬於既有允許型態。
- 成交量達基本門檻，且不是無量硬拉。
- 籌碼或法人偏多；若資料缺失，只能保守列為觀察。

## 舊 Agent 對應

- `primary_review` -> `primary`
- `secondary_watchlist` -> `secondary`
- `lower_priority` 或 `reject` -> `reject`

## 禁止事項

- 不判斷當沖切入點。
- 不輸出 enter。
- 不因分數高就直接買進。

## 待補

- 籌碼分數如何影響 primary / secondary。
- 法人資料如何加入。
- 無量股與爆量不漲的量化門檻。
