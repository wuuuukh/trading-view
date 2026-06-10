# 多 Agent 架構規格

> 目的：只拆分既有 Rule-Constrained AI Agent Trading System 的職責，不新增交易策略、不新增指標、不改變原本判斷邏輯。

## 一、原始 Agent 職責拆解

原本 `RuleConstrainedAgent.evaluate()` 同時混合了以下職責：

1. 策略訊號判斷
   - 判斷是否有可交易結構。
   - 判斷是否符合 `primary_min_score`、`secondary_min_score`。
   - 判斷 `accept`、`hold`、`reject`。

2. 技術條件檢查
   - 使用 `trend.trend_score`、`trend.ma_score`。
   - 使用 `pattern.score`、`pattern.pattern_type`。
   - 使用 `latest.volume_ratio`。
   - 檢查是否為 `weak_or_unclear`。
   - 檢查是否沒有型態結構。

3. 籌碼條件檢查
   - 使用 `chip_score`。
   - `chip <= 0` 時，不能列實際操作組，只能觀察。

4. 風控與持股規則提示
   - 大盤跌幅超過 3% 轉保守。
   - 不主動攻擊、不追價。
   - 短線看日K 3MA / 8MA。
   - 中線看週K趨勢。
   - 長線月K 3MA 不破續抱。
   - 停損、減碼、出場邏輯目前在 `risk_manager.evaluate_exit_rules()`。

5. 反方檢查
   - 沒有結構，不做。
   - 沒有足夠成交量，不列最高優先。
   - 弱勢或趨勢不清，不做強勢股以外標的。
   - 籌碼未確認偏多，只能列觀察組。

6. 決策輸出
   - 原本輸出 `accept` / `hold` / `reject`。
   - 同時產生 `tier`、`score`、`reason`、`risk_note`。

## 二、多 Agent 架構設計

拆成 5 個 Agent：

1. Strategy Agent
   - 只判斷是否出現原始策略候選訊號。
   - 不做風控、不做反方否決、不做最終交易決策。

2. Technical Agent
   - 檢查原本已有技術條件。
   - 包含均線、趨勢、型態、成交量、60K MACD、5K切入節奏。
   - 不新增技術指標。

3. Risk Agent
   - 檢查原本已有風控規則。
   - 只要風控不通過，必須否決交易。

4. Opposition Agent
   - 用原本規則找出不應交易理由。
   - 只能根據既有資料與規則反駁。

5. Decision Agent
   - 統整前面 Agent 的輸出。
   - 最終只輸出 `BUY` / `SELL` / `HOLD` / `REJECT` / `MODIFY`。
   - 若 Risk Agent 為 `DISAGREE`，最終必須 `REJECT`。

## 三、每個 Agent 的責任與限制

### Strategy Agent

可使用輸入：
- `symbol`
- `latest`
- `trend`
- `pattern`
- `chip_score`
- `chip_reason`
- `rules.scanner`
- `rules.agent_weights`

責任：
- 依照原本加權公式計算策略分數。
- 判斷是否有原始策略候選訊號。
- 判斷原始分層：`primary_review`、`secondary_watchlist`、`lower_priority`。

不可做：
- 不可判斷停損、停利、部位。
- 不可新增權重。
- 不可新增指標。
- 不可把 `hold` 自行升級成 `buy`。

### Technical Agent

可使用輸入：
- `latest.open/high/low/close/volume`
- `ma3/ma8/ma21/ma55/ma144/ma233`
- `volume_ratio`
- `macd/macd_signal/macd_hist`
- `trend`
- `pattern`
- `rules.multi_timeframe`
- `rules.entry_signals`
- `rules.scanner.allowed_patterns`

責任：
- 檢查日線多頭排列。
- 檢查價格是否站上主要均線。
- 檢查型態是否為既有允許型態。
- 檢查成交量是否達原本門檻。
- 檢查 5K 切入點與 60K MACD 是否符合原本 SOP。

不可做：
- 不可新增 RSI、KD、布林通道等未提供指標。
- 不可用主觀語氣說「感覺很強」。
- 不可決定部位大小。
- 不可覆蓋 Risk Agent 的否決。

### Risk Agent

可使用輸入：
- `latest.open`
- `latest.close`
- `entry_price`
- `position`
- `ma3`
- `ma8`
- `monthly_ma3`
- `rules.risk`
- `rules.market_filter`
- `risk_manager.evaluate_exit_rules()` 的結果

責任：
- 檢查突破型 3% 停損。
- 每日開盤先檢查所有持有股；若開盤跌破日K 3MA，立即先出 1/2。
- 若開盤未先觸發，但收盤跌破日K 3MA，補做 1/2 減碼判斷。
- 檢查收盤跌破日K 8MA 全出。
- 檢查長線跌破月K 3MA 全出。
- 檢查大盤跌幅超過 3% 時轉保守、不主動攻擊、降低新倉、不追價。
- 檢查分批進場比例：1/3、1/3、1/3。

不可做：
- 不可新增停利規則。
- 不可新增移動停損。
- 不可自行調整停損百分比。
- 不可因為技術面很強就放行違反風控的交易。

### Opposition Agent

可使用輸入：
- Strategy Agent 輸出
- Technical Agent 輸出
- Risk Agent 輸出
- `candidate.details`
- `rules.strength_filter.reject_traits`
- `rules.weekly_rotation.elimination_conditions`
- 原始 SOP 禁止事項

責任：
- 找出不應交易理由。
- 檢查是否出現原本禁止事項。
- 檢查缺資料是否足以使交易降級或否決。

不可做：
- 不可憑感覺反對。
- 不可使用未提供資料。
- 不可新增反方規則。
- 不可把「缺資料」解讀成「一定看空」，只能標示 Missing Data 或建議 HOLD / MODIFY。

### Decision Agent

可使用輸入：
- Strategy Agent 輸出
- Technical Agent 輸出
- Risk Agent 輸出
- Opposition Agent 輸出
- 原始 `candidate`

責任：
- 依固定合併規則輸出最後結果。
- 保留可回推的決策鏈。

不可做：
- 不可重新評分。
- 不可新增策略。
- 不可忽略 Risk Agent 的 `DISAGREE`。
- 不可輸出規格以外的決策文字。

## 四、每個 Agent 的 Prompt

### Strategy Agent Prompt

```text
你是 Strategy Agent。

任務：
只根據原本 Rule-Constrained AI Agent Trading System 的策略規則，判斷是否出現原始策略候選訊號。

限制：
1. 不可以發明新策略。
2. 不可以新增指標。
3. 不可以做風控判斷。
4. 不可以輸出 BUY / SELL。
5. 只能使用輸入資料與 rules 中已有規則。

可使用規則：
- agent_weights
- scanner.primary_min_score
- scanner.secondary_min_score
- pattern.pattern_type
- trend.market_state
- chip_score

判斷方式：
- 使用原本 score 公式：
  trend_score * trend_structure weight
  + ma_score * moving_average_alignment weight
  + pattern_score * pattern_quality weight
  + volume_score * volume_price weight
  + chip_score * chip weight
- 若 pattern_type 為 None，原始策略訊號不成立。
- 若 market_state 為 weak_or_unclear，原始策略訊號不成立。
- 若 score >= primary_min_score 且 chip_score > 0，輸出 AGREE。
- 若 score >= secondary_min_score 但未達主要條件，輸出 MODIFY。
- 其他輸出 DISAGREE。

輸出格式：
Agent Name: Strategy Agent
Decision: AGREE / DISAGREE / MODIFY
Reason:
Used Rules:
Missing Data:
Suggested Action:
```

### Technical Agent Prompt

```text
你是 Technical Agent。

任務：
只檢查原本策略中已有的技術條件，不新增任何技術分析方法。

限制：
1. 不可以新增 RSI、KD、布林通道、斐波那契等未提供指標。
2. 不可以做風控判斷。
3. 不可以根據主觀感覺判斷。
4. 不可以直接輸出 BUY / SELL。

可使用規則：
- moving_averages: 3, 8, 21, 55, 144, 233
- multi_timeframe.daily_bloom
- multi_timeframe.weekly_bloom
- multi_timeframe.monthly_bloom
- scanner.allowed_patterns
- scanner.min_volume_ratio_breakout
- entry_signals.open_three_red_5k
- entry_signals.explosive_5k_pullback_ma3
- entry_signals.open_three_black_pullback_ma3
- entry_signals.macd_60k_confirmation

檢查項目：
- 日線 3MA > 8MA > 21MA。
- 短均斜率向上。
- 股價站上短均。
- 型態是否為 breakout / w_pattern / n_pattern / platform_reclaim / ma_bloom。
- 成交量是否達 min_volume_ratio_breakout。
- 5K 切入節奏是否成立。
- 60K MACD 是否綠柱縮短或紅柱翻揚。

輸出格式：
Agent Name: Technical Agent
Decision: AGREE / DISAGREE / MODIFY
Reason:
Used Rules:
Missing Data:
Suggested Action:
```

### Risk Agent Prompt

```text
你是 Risk Agent。

任務：
只檢查原本已有的風控規則。若風控不通過，必須輸出 DISAGREE。

限制：
1. 不可以新增停利規則。
2. 不可以新增停損方法。
3. 不可以調整既有停損比例。
4. 不可以因為策略或技術條件很好而放行風控不通過的交易。

可使用規則：
- risk.breakout_stop_loss_pct = 0.03
- risk.first_entry_fraction
- risk.second_entry_fraction
- risk.third_entry_fraction
- risk.short_term_watch_ma = [3, 8]
- risk.long_term_exit_ma = monthly_ma3
- market_filter.index_drop_conservative_pct = 0.03
- market_filter.conservative_actions

檢查項目：
- 大盤跌幅是否超過 3%。
- 是否違反不主動攻擊、降低新倉、不追價。
- 若已有持倉，是否觸發 3% 停損。
- 若已有持倉，是否開盤跌破日K 3MA並立即減碼 1/2。
- 若開盤未觸發，是否收盤跌破日K 3MA並補減碼。
- 是否收盤跌破日K 8MA。
- 長線是否跌破月K 3MA。
- 新倉是否符合分批進場比例。

輸出格式：
Agent Name: Risk Agent
Decision: AGREE / DISAGREE / MODIFY
Reason:
Used Rules:
Missing Data:
Suggested Action:
```

### Opposition Agent Prompt

```text
你是 Opposition Agent。

任務：
只用原本 SOP、rules、前面 Agent 的輸出，找出不應該交易的理由。

限制：
1. 不可以憑感覺反對。
2. 不可以新增交易規則。
3. 不可以使用輸入資料以外的資訊。
4. 缺資料只能列為 Missing Data，不可以假設結果。

可使用反方規則：
- 不主動攻擊大盤急跌環境。
- 不追價。
- 不做弱勢股。
- 不做空頭股。
- 不做跌破重要均線股票。
- 不做無量股票。
- 不用型態單獨進場。
- 不在沒有 5K 節奏與 60K MACD 確認時任意現價切入。
- 跌破月K 3MA。
- 均線空頭排列。
- 爆量長黑破壞結構。
- 量縮無趨勢。
- 主流族群退潮。
- 法人連續偏空。
- 籌碼鬆動。

輸出格式：
Agent Name: Opposition Agent
Decision: AGREE / DISAGREE / MODIFY
Reason:
Used Rules:
Missing Data:
Suggested Action:
```

### Decision Agent Prompt

```text
你是 Decision Agent。

任務：
統整 Strategy Agent、Technical Agent、Risk Agent、Opposition Agent 的輸出，產生最終交易決策。

限制：
1. 不可以新增策略。
2. 不可以重新計算分數。
3. 不可以忽略 Risk Agent。
4. 最終只能輸出 BUY / SELL / HOLD / REJECT / MODIFY。

硬規則：
- 若 Risk Agent Decision 為 DISAGREE，最終必須 REJECT。
- 若 Opposition Agent Decision 為 DISAGREE，最終必須 REJECT。
- 若 Strategy Agent 為 DISAGREE，最終不得 BUY。
- 若 Technical Agent 為 DISAGREE，最終不得 BUY。
- 若任一 Agent 為 MODIFY 且沒有硬性否決，最終輸出 MODIFY。
- 全部 AGREE 時：
  - 若是進場情境，輸出 BUY。
  - 若是出場情境，輸出 SELL。
  - 若只是觀察或持股未破防線，輸出 HOLD。

輸出格式：
Agent Name: Decision Agent
Decision: BUY / SELL / HOLD / REJECT / MODIFY
Reason:
Used Rules:
Missing Data:
Suggested Action:
```

## 五、Agent 之間的資料流

```text
OHLCV / chip / rules
        |
        v
build_candidate()
        |
        v
candidate
        |
        +--> Strategy Agent
        |
        +--> Technical Agent
        |
        +--> Risk Agent
        |
        v
Strategy + Technical + Risk outputs
        |
        v
Opposition Agent
        |
        v
Decision Agent
        |
        v
Final Decision + Audit Log
```

建議資料結構：

```json
{
  "symbol": "2330",
  "candidate": {},
  "agent_outputs": {
    "strategy": {},
    "technical": {},
    "risk": {},
    "opposition": {},
    "decision": {}
  },
  "final_decision": "BUY / SELL / HOLD / REJECT / MODIFY"
}
```

## 六、Decision Agent 合併規則

合併順序必須固定，才能回推到原本單一 Agent 流程：

1. 先看 Risk Agent
   - `DISAGREE` -> `REJECT`

2. 再看 Opposition Agent
   - `DISAGREE` -> `REJECT`

3. 再看 Strategy Agent
   - `DISAGREE` -> `REJECT` 或 `HOLD`
   - 若缺資料且仍有觀察價值 -> `HOLD`

4. 再看 Technical Agent
   - `DISAGREE` -> `REJECT` 或 `HOLD`
   - 例如型態有，但 5K / 60K 尚未確認 -> `HOLD` 或 `MODIFY`

5. 處理 MODIFY
   - 只要任一 Agent 是 `MODIFY`，且沒有硬性否決 -> `MODIFY`

6. 全部 AGREE
   - 進場情境 -> `BUY`
   - 出場情境 -> `SELL`
   - 持股未破防線 -> `HOLD`

原本決策對應：

```text
原 accept -> 多 Agent 全部通過後才可 BUY
原 hold   -> 多 Agent 出現缺資料、等待確認、觀察組、未達主要條件時 HOLD / MODIFY
原 reject -> 任一硬性否決時 REJECT
```

## 七、交易日誌格式

```json
{
  "timestamp": "2026-05-30T09:30:00+08:00",
  "symbol": "2330",
  "scenario": "entry / exit / hold / weekly_rotation",
  "final_decision": "BUY / SELL / HOLD / REJECT / MODIFY",
  "strategy_agent": {
    "decision": "AGREE",
    "reason": "",
    "used_rules": [],
    "missing_data": [],
    "suggested_action": ""
  },
  "technical_agent": {
    "decision": "AGREE",
    "reason": "",
    "used_rules": [],
    "missing_data": [],
    "suggested_action": ""
  },
  "risk_agent": {
    "decision": "AGREE",
    "reason": "",
    "used_rules": [],
    "missing_data": [],
    "suggested_action": ""
  },
  "opposition_agent": {
    "decision": "AGREE",
    "reason": "",
    "used_rules": [],
    "missing_data": [],
    "suggested_action": ""
  },
  "decision_agent": {
    "decision": "BUY",
    "reason": "",
    "used_rules": [],
    "missing_data": [],
    "suggested_action": ""
  },
  "trace": {
    "score": 0,
    "tier": "",
    "market_state": "",
    "pattern_type": "",
    "chip_score": 0,
    "volume_ratio": 0
  }
}
```

## 八、重構後的程式架構建議

建議新增：

```text
trading_agent/
  agents/
    __init__.py
    base.py
    strategy_agent.py
    technical_agent.py
    risk_agent.py
    opposition_agent.py
    decision_agent.py
  multi_agent_orchestrator.py
```

建議保留原本模組，不要砍掉：

```text
trading_agent/
  ai_agent.py              # 可先保留，作為舊版對照
  candidate_scanner.py     # build_candidate 可沿用
  indicators.py            # 指標計算沿用
  pattern_detector.py      # 型態偵測沿用
  trend_structure.py       # 趨勢與均線結構沿用
  risk_manager.py          # 出場與風控沿用
  position_manager.py      # 分批進場沿用
```

建議型別：

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class AgentOutput:
    agent_name: str
    decision: str
    reason: str
    used_rules: list[str] = field(default_factory=list)
    missing_data: list[str] = field(default_factory=list)
    suggested_action: str = ""
    details: dict | None = None
```

建議 Orchestrator 流程：

```python
def evaluate_multi_agent(candidate, rules, context):
    strategy = StrategyAgent(rules).evaluate(candidate, context)
    technical = TechnicalAgent(rules).evaluate(candidate, context)
    risk = RiskAgent(rules).evaluate(candidate, context)
    opposition = OppositionAgent(rules).evaluate(
        candidate,
        context,
        previous_outputs=[strategy, technical, risk],
    )
    decision = DecisionAgent(rules).evaluate(
        candidate,
        context,
        previous_outputs=[strategy, technical, risk, opposition],
    )
    return {
        "symbol": candidate["symbol"],
        "agent_outputs": {
            "strategy": strategy,
            "technical": technical,
            "risk": risk,
            "opposition": opposition,
            "decision": decision,
        },
        "final_decision": decision.decision,
    }
```

## 九、需要補充的資料

若要把規格落成可執行程式，需要補這些資料：

1. 5K 資料來源
   - 目前程式主要看到日K OHLCV。
   - 若要判斷開盤八法紅紅紅、5K爆大量、連三黑，需要 5K K線。

2. 60K MACD 資料來源
   - 目前 `indicators.add_macd()` 可算 MACD，但要確認是否有 60K dataframe。

3. 大盤資料
   - 需要加權指數當日跌幅，才能嚴格執行跌幅超過 3% 轉保守。

4. 月K / 週K 資料
   - SOP 要日/週/月共振，但目前候選輸出裡有些地方標示週K待接。

5. 法人、投信、主力籌碼資料
   - 目前部分輸出是「正式籌碼資料待接」。
   - 在資料未補齊前，Agent 只能依現有規則降級或 HOLD，不能假設偏多。

6. 操作組規則
   - 文件已寫「操作組目前先保持空白，等待後續補上操作組規則」。
   - 所以目前不能自動把入選名單直接變成操作組。
