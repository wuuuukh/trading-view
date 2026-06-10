# 06 決策 / 風控裁判 操作草稿

## 角色定位

決策 / 風控裁判是最後審核者。只有它可以輸出最終操作，不負責選股，也不負責創造策略。

## 輸入資料

- IndexAgent 結果
- Candidate Scanner 結果
- Strategy Router 結果
- Long Swing Agent 結果
- Intraday Agent 結果
- Day Trade Agent 結果
- 目前持股
- 資金水位
- 停損規則

資料待補：

- 真實持股資料
- 資金水位
- 單筆部位上限
- 當沖與波段是否共用資金池
- 當前模擬是否允許當沖

## 輸出格式

```json
{
  "agent_name": "decision_risk_controller",
  "symbol": "6141",
  "action": "enter / wait / reject / reduce / exit",
  "position_size": "none / small / normal",
  "reason": ""
}
```

## 硬規則草稿

大盤：

- IndexAgent = risk_off 時，不允許 enter。
- risk_off 且有持股，可以 reduce / exit。
- cautious 時，enter 預設降級為 wait 或 small。

股票初篩：

- Candidate Scanner = reject，最終必須 reject。
- secondary 不可直接進場，除非後續 Agent 給出完整確認。

策略路由：

- route = reject，最終 reject。
- route = watch，最終 wait。
- route = long_hold，只看 Long Swing Agent 的結果。
- route = intraday，只看 Intraday Agent 的盤中切入結果。
- route = day_trade，只有在標的可當沖且目前策略允許當沖時，才看 Day Trade Agent 的結果；否則最終必須 reject 或 wait。

持股狀態：

- 沒有持股，不可 reduce / exit。
- 有持股且跌破風控線，優先 reduce / exit。

衝突處理：

- 風控優先於進場。
- risk_off 優先於所有個股訊號。
- 盤中切入 enter_now 只代表盤中切入，不代表當沖。
- 當沖必須同時通過「標的可當沖、策略允許、盤中條件、當日出場規則」四項檢查。

## 待補

- position_size 的計算方式。
- enter 的資金比例。
- 當沖與長期持有同檔股票衝突時如何處理。
