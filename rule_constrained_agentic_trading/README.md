# Rule-Constrained AI Agent Trading System

這是一套圍繞個人交易 SOP、操作思維、均線系統、型態邏輯與籌碼面選股規則所設計的 rule-constrained AI Agent Trading 系統。

系統定位是研究型、自動化輔助型交易系統，不接真實券商 API、不做真實下單、不做 webhook。Agent 不是自由交易員，而是可解釋的規則執行與決策輔助層。

## 系統設計

1. 市場資料輸入：載入 OHLCV，支援多週期資料夾。
2. 籌碼面初篩：計算大股東每週持股張數變化、門檻分級、前 30 名同步增加。
3. 趨勢與型態辨識：固定使用 3 / 8 / 21 / 55 / 144 / 233 MA，辨識 W、突破、N 字。
4. 候選股篩選：以技術結構 + 多週期均線 + 籌碼累積共振排序。
5. AI Agent 評分與決策：輸出 accept / reject / hold、score、reason、market_state、pattern_type、risk_note。
6. 風控與部位管理：分批進場、3% 突破型停損、跌破 3MA 減碼、跌破 8MA 全出、長線看月K 3MA。
7. 回測 / paper trading：提供 baseline vs agent 比較與研究用模擬。
8. 人工可讀報告：輸出 JSON / CSV / Markdown。

## MVP 開發順序

1. 建立資料格式、設定檔與 CLI。
2. 實作固定均線、成交量與 MACD 輔助指標。
3. 實作籌碼資料模型與可配置評分。
4. 實作 W / Breakout / N 字型態偵測初版。
5. 實作 candidate scanner 與 watchlist 分層。
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

