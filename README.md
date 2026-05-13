# Rule-Constrained AI Agent Trading System

這是一套圍繞個人交易 SOP、操作思維、均線系統、型態邏輯與籌碼面選股規則所設計的 rule-constrained AI Agent Trading 系統。

系統定位是研究型、自動化輔助型交易系統，不接真實券商 API、不做真實下單、不做 webhook。Agent 不是自由交易員，而是可解釋的規則執行與決策輔助層。

## 系統設計

1. 市場資料輸入：載入 OHLCV，支援日K、週K、月K與盤中週期資料夾。
2. 大盤過濾：加權指數跌幅超過 3% 時轉保守，不主動攻擊、不追價、降低新倉。
3. 籌碼面初篩：計算大股東每週持股張數變化、門檻分級、前 30 名同步增加，並保留法人、投信、主力籌碼欄位。
4. 趨勢與型態辨識：固定使用 3 / 8 / 21 / 55 / 144 / 233 MA，辨識 W、突破、N 字、平台整理轉強與均線開花。
5. 候選股篩選：以強勢股條件 + 型態 + 日/週/月均線共振 + 籌碼偏多排序。
6. AI Agent 評分與決策：輸出 accept / reject / hold、score、reason、market_state、pattern_type、risk_note。
7. 切入確認：最後才檢查 5K 開盤節奏與 60K MACD，符合 SOP 才允許現價切入。
8. 風控與部位管理：短線看日K 3MA / 8MA，中線看週K趨勢，長線看月K 3MA。
9. 每週日更新選股池：分實際操作組與觀察組，降級股票保留觀察 1 週，未轉強自動淘汰。
10. 回測 / paper trading：提供 baseline vs agent 比較與研究用模擬。
11. 人工可讀報告：輸出 JSON / CSV / Markdown。

## MVP 開發順序

1. 建立資料格式、設定檔與 CLI。
2. 實作固定均線、成交量與 MACD 輔助指標。
3. 實作籌碼資料模型與可配置評分。
4. 實作 W / Breakout / N 字型態偵測初版。
5. 實作 candidate scanner 與實際操作組 / 觀察組分層。
6. 實作 rule-constrained AI Agent 評分與決策說明。
7. 實作風控、部位管理、回測與 paper trading。
8. 輸出 JSON / CSV / Markdown 報告。

## 專案結構

```text
rule_constrained_agentic_trading/
  config/rules.yaml
  data/ohlcv/
  data/chip/
  reports/
  trading_agent/
    data_loader.py
    chip_loader.py
    indicators.py
    pattern_detector.py
    trend_structure.py
    candidate_scanner.py
    ai_agent.py
    risk_manager.py
    position_manager.py
    backtest.py
    paper_trading.py
    reporter.py
    cli.py
```

## 資料格式

OHLCV CSV：

```csv
timestamp,open,high,low,close,volume
2026-01-02,100,103,99,102,120000
```

籌碼 CSV：

```csv
symbol,week,holder_rank,shares
2330,2026-W01,1,120000
2330,2026-W02,1,121000
```

`shares` 以張數為單位。籌碼資料頻率固定標記為 weekly，避免與日線資料混淆。

## 使用

```powershell
pip install -r requirements.txt
python -m trading_agent.cli scan --ohlcv data/ohlcv --chip data/chip/shareholders.csv --out reports
python -m trading_agent.cli paper --ohlcv data/ohlcv --chip data/chip/shareholders.csv --out reports
```
