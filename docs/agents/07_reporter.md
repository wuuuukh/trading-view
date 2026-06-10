# 07 Reporter 輸出結果 操作草稿

## 角色定位

Reporter 不是交易 Agent，而是輸出模組。它負責把 multi-agent 結果整理成 JSON、CSV、Markdown、Dashboard 顯示。

## 輸入資料

- multi-agent pipeline JSON
- 原始 scan / paper_scan / weekly_selection 結果
- next_trading_plan
- 後驗追蹤資料

## 輸出清單

今日候選：

- symbol
- name
- candidate_rank
- route
- final_action
- score
- reason
- risk_note

長期 / 波段持有名單：

- symbol
- name
- action: build / add / hold / reduce / exit / wait
- key_level
- stop_level
- 持股狀態
- 操作理由

盤中切入觀察名單：

- symbol
- name
- intraday_action
- entry_zone
- 5K 狀態
- 60K MACD 狀態
- 風控提醒
- 注意：盤中切入觀察不是當沖；買進後仍依不能當沖與 3MA / 8MA 規則管理。

淘汰名單：

- symbol
- name
- reject_reason
- 重新觀察條件

## 目前狀態

目前已能輸出 JSON：

```powershell
python -m trading_agent.cli multiagent --index-daily data\index\taiex_daily.csv --ohlcv data\ohlcv --out reports\multi_agent_latest.json
```

## 待補

- CSV 欄位設計。
- Markdown 報表版型。
- Dashboard 顯示區塊。
- 是否要把四類名單分成不同 tab。
