# 08 Performance Tracker 後驗追蹤 操作草稿

## 角色定位

Performance Tracker 不是交易 Agent，而是復盤模組。它負責追蹤原本判斷在 1D / 3D / 5D、長期持有、盤中切入後的結果。

## 輸入資料

- 決策當日的 final_action
- 決策當日價格
- 後續 1D / 3D / 5D 收盤價
- 長期持有期間價格
- 盤中切入後的持股與防守紀錄

資料待補：

- 盤中切入實際成交紀錄
- 長期持有真實部位資料
- 後驗追蹤更新頻率

## 輸出格式

```json
{
  "symbol": "6141",
  "decision_date": "2026-06-02",
  "original_action": "wait",
  "route": "watch",
  "return_1d": null,
  "return_3d": null,
  "return_5d": null,
  "review": ""
}
```

## 追蹤草稿

1D / 3D / 5D：

- 追蹤決策後 1、3、5 個交易日報酬。
- 用來驗證 `enter / wait / reject` 是否合理。
- 不把單次結果直接當成策略好壞結論。

長期持有：

- 追蹤是否守住日 3MA / 8MA / 月 3MA。
- 追蹤是否符合原本續抱、減碼、出場判斷。

盤中切入：

- 追蹤 enter_now 後的實際損益。
- 追蹤 wait_pullback 是否真的給到更好位置。
- 追蹤 avoid 是否避開風險。
- 注意：盤中切入不是當沖，不用同日出場績效衡量。

## 待補

- 盤中切入後的 1D / 3D / 5D 績效計算方式。
- 多次進出如何記錄。
- 交易成本與滑價。
- 後驗分數如何回饋到策略調整。
