# 04 長期 / 波段持有 Agent 操作草稿

## 角色定位

長期 / 波段持有 Agent 只處理 `route = long_hold` 的股票，負責建倉、加碼、續抱、減碼、出場與等待。

這份規則只抽取原始 Agent 與既有 SOP 中跟長期 / 波段持有有關的內容；當沖切入、純選股排序、績效追蹤與報告輸出不放在這裡。

## 輸入資料

- 個股日 K / 週 K / 月 K
- 目前是否持股
- 成本與部位
- 3MA / 8MA / 月 3MA
- 加權指數 Agent 結果
- Candidate Scanner 結果
- 風控規則
- `risk_manager.evaluate_open_exit_rules()` 結果
- `risk_manager.evaluate_exit_rules()` 結果
- `config/rules.yaml` 的 `risk` 與 long-hold 相關規則

資料待補：

- 真實持股清單與成本資料來源
- 月 K 3MA 是否已有穩定資料
- 週 K / 月 K 是否由日 K 重採樣，或另接資料源

## 輸出格式

```json
{
  "agent_name": "long_swing_agent",
  "symbol": "6141",
  "action": "build / add / hold / reduce / exit / wait / skip",
  "reason": "",
  "key_level": null,
  "stop_level": null
}
```

## 操作草稿

`skip`：

- route 不是 `long_hold`。

`wait`：

- 沒有持股，且日 / 週 / 月結構、5K 節奏或 60K MACD 尚未確認。
- 大盤 `risk_off` 時，不開新倉。
- 大盤 `cautious` 時，不主動攻擊；已有候選也先等回測或轉強確認。
- Candidate Scanner 只給觀察組，或籌碼尚未確認偏多時，不自行升級成建倉。
- 日 K 已跌破 3MA 且尚未站回，先等待，不追價。

`build`：

- 沒有持股，且 `route = long_hold`。
- 大盤不是 `risk_off`，且個股通過強勢股、型態、日 / 週 / 月均線共振與籌碼檢查。
- 日 K 結構完整，至少沒有跌破日 K 3MA / 8MA 的核心防線。
- 週 K 趨勢未轉弱，月 K 3MA 未跌破。
- 正常建倉仍需等待 5K 切入節奏，並搭配 60K MACD 不轉弱或轉強確認。
- 不追高；若已遠離日 K 3MA / 8MA 或週月支撐，改輸出 `wait`。

`add`：

- 已持股。
- 原持股仍未觸發 `risk_manager.evaluate_exit_rules()` 的減碼或出場。
- 回測日 K 3MA、日 K 8MA，或週 K / 月 K 3MA 交會支撐不破。
- 月 K 3MA 未跌破，週 K 結構未爆量轉弱。
- 盤中重新轉強，且 60K MACD 沒有明顯轉弱。
- 加碼資金比例沿用 `config/rules.yaml` 的 `risk.first_entry_fraction`、`second_entry_fraction`、`third_entry_fraction`，不在本 Agent 自行改比例。
- 不追高加碼；價格離支撐太遠時輸出 `hold` 或 `wait`。

`hold`：

- 已持股。
- `risk_manager.evaluate_exit_rules(..., long_term=True)` 回傳 `hold`。
- 沒跌破日 K 3MA / 8MA 的核心防線。
- 月 K 3MA 未破。
- 週 K 結構未爆量轉弱。
- 原始 Agent 的長抱原則為：短線看日 K 3MA / 8MA，中線看週 K 趨勢，長線月 K 3MA 不破續抱。

`reduce`：

- 已持股，且不能用在沒有部位的股票。
- 每日開盤若持有股開盤價跌破日 K 3MA，先依 `risk_manager.evaluate_open_exit_rules()` 輸出 `reduce`。
- 開盤跌破日 K 3MA 時立即出售 1/2，不等收盤確認。
- `risk_manager.evaluate_exit_rules()` 回傳 `reduce` 時，輸出 `reduce`。
- 若開盤未先觸發，但收盤跌破日 K 3MA，才補做 1/2 減碼判斷。
- 只做既有減碼，不新增移動停損或自行調整減碼比例。

`exit`：

- 已持股，且不能用在沒有部位的股票。
- `risk_manager.evaluate_exit_rules()` 回傳 `exit_all` 時，輸出 `exit`。
- 突破型買進後，收盤價相對進場價虧損達 `risk.breakout_stop_loss_pct = 0.03`，立即出場。
- 收盤跌破日 K 8MA，全出。
- 長期持有跌破月 K 3MA，全出。
- 週 K / 月 K 爆量長黑破壞結構時，不自行找理由續抱，需交給風控規則判斷是否出場。

## 來源對照

- 原始 Agent 風險備註：依序檢查大盤、強勢股、型態、日 / 週 / 月均線共振、籌碼、60K MACD 與 5K 開盤節奏。
- 原始 Agent 長抱原則：短線看日 K 3MA / 8MA，中線看週 K 趨勢，長線月 K 3MA 不破續抱。
- `risk_manager.evaluate_open_exit_rules()`：負責每日開盤持有股跌破日 K 3MA 時立即減碼 1/2。
- `risk_manager.evaluate_exit_rules()`：負責既有 3% 停損、收盤跌破日 K 3MA 補減碼、跌破日 K 8MA 出場、長線跌破月 K 3MA 出場。
- `config/rules.yaml`：保留 `breakout_stop_loss_pct = 0.03`、三段建倉資金比例與 `long_term_exit_ma = monthly_ma3`。

## 禁止事項

- 不處理當沖。
- 大盤 risk_off 不可建倉。
- 沒有持股不可輸出 reduce / exit。
- 不新增技術指標。
- 不新增移動停損。
- 不自行調整 3% 停損或 1/2 減碼比例。
- 不把觀察組或籌碼未確認標的直接升級成建倉。

## 待補

- 持股成本與部位資料。
- 月 K 3MA 出場的實際資料欄位。
- 週 K / 月 K 資料來源與更新時點。
