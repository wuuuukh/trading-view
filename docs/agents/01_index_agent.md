# 01 加權指數 Agent 操作草稿

## 角色定位

加權指數 Agent 是整套系統的大盤總開關。它只判斷今天市場環境，不選股、不決定個股買賣。

## 輸入資料

- 加權指數日 K、週 K、月 K
- 加權指數 5K、60K
- 當日漲跌幅
- 成交量與量比
- 3MA / 8MA / 21MA / 55MA / 144MA / 233MA

資料待補：

- 加權指數 5K / 60K 穩定資料來源
- 加權指數週 K / 月 K 是否由日 K 重採樣，或另接資料源
- 漲跌家數、類股輪動、台指期方向

## 輸出格式

```json
{
  "agent_name": "index_agent",
  "market_bias": "bullish / neutral / weak / risk_off",
  "operation_mode": "aggressive / normal / cautious / risk_off",
  "index_score": 0,
  "allow_new_position": false,
  "allow_chasing": false,
  "position_adjustment": "normal / reduce / no_new_position",
  "reason": ""
}
```

## 操作草稿

`risk_off`：

- 加權指數當日跌幅超過 3%。
- 加權指數跌破日 K 8MA 且 3MA / 8MA 轉弱。
- 只允許觀察、減碼、出場，不允許新倉。

`cautious`：

- 指數未達 risk_off，但跌破短均或 3MA 沒有站在 8MA 上方。
- 個股再強也不追價。
- 波段新倉降級為 wait，當沖只能等乾淨切入點。

`normal`：

- 日 K 結構尚可，但週 K / 月 K 沒有完全同步。
- 可以做股票初篩與觀察，但不能解讀成全面攻擊。

`aggressive`：

- 日 K、週 K、月 K 均線同向偏多。
- 短中長均線結構完整。
- 允許後續 Agent 對強勢股採取較積極判斷。

## 禁止事項

- 不選股。
- 不輸出 enter。
- 不覆蓋個股風控。
- 不因單一強勢股而改變大盤結論。

## 待補

- 盤中 5K / 60K 如何修正 `operation_mode`。
- 台指期是否納入。
- 類股輪動是否納入。
