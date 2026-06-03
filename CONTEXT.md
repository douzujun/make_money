# Domain Glossary — Vestoria Data Terminal

## 投资仪表盘 (Investment Dashboard)

A standalone page in the frontend that displays independent market scores for 4 markets. Each market shows two independent scores: 长期分 and 每日分. No composite global score exists — markets are always shown independently.

## 长期分 (Long-term Score)

A 0–100 score representing macro trend health for a given market, based on the percentage deviation of the current price from its 200-day moving average (MA200). Changes on a quarterly timescale. Displayed as: 档位 label + numeric score (e.g., "偏高 (72/100)").

Calculation: maps MA200 deviation % to a 0–100 score using the existing `ma200` indicator grade logic.

## 每日分 (Daily Score)

A 0–100 score representing short-term market sentiment for a given market. Changes on a daily timescale. Displayed as: 档位 label + numeric score. Calculation method differs by market type:

- **A股 / 港股**: 14-day RSI of the index price. RSI < 30 = oversold (low score), RSI > 70 = overbought (high score).
- **黄金**: Inverse of GVZ (CBOE Gold Volatility Index). High volatility = fear = low score.
- **原油**: Inverse of OVX (CBOE Crude Oil Volatility Index). High volatility = fear = low score.

## 市场覆盖范围 (Covered Markets)

| 市场 | 代表标的 | yfinance Symbol |
|------|---------|----------------|
| A股 | 沪深300 | 000300.SS |
| 港股 | 恒生指数 | ^HSI |
| 黄金 | 黄金期货 | GC=F |
| 原油 | WTI原油期货 | CL=F |

## 档位 (Grade)

A categorical label paired with a numeric score that describes the interpretation of a score range. Example grades: 极度低估 / 低估 / 偏低 / 合理 / 偏高 / 高估 / 极度高估 (for MA200-based scores); 极度超卖 / 超卖 / 中性 / 超买 / 极度超买 (for RSI-based scores).

## 板块资金流 (Sector Fund Flow)

A standalone page showing A-share industry and concept sector money flow data. Two dimensions: 行业板块 (~30 industries, for trend analysis) and 概念板块 (concept hot board, for short-term sentiment). Data is fetched from AkShare (东方财富) and stored daily at 16:00.

## 行业板块 (Industry Sector)

Broad industry classification (~30 sectors: 电子, 医药生物, 机械设备, etc.) used for tracking capital rotation trends. Semiconductor stocks fall under 电子; robot stocks fall under 机械设备. Historical fund flow stored in `sector_fund_flow` DB table.

## 概念板块 (Concept Sector)

Fine-grained thematic groupings (300+ concepts: 半导体, 机器人, AI算力, etc.). Used only as a daily hot board (今日净流入 Top10), not stored historically due to noise.

## 明日信号 (Next-Day Signal)

A composite prediction signal per industry sector. Score = (资金流动量 × 40%) + (价格动量 × 40%) + (全局风险调整 × 20%). Inputs: consecutive net-inflow days + 5-day net flow ratio (fund flow); 5-day sector return (price momentum); inverse VIX score from existing system (global risk). Outputs a directional label: 看多 / 中性 / 看空, plus a historical win-rate from back-tested data.

## 资金动量 (Fund Flow Momentum)

A derived metric for each industry sector. Combines: (1) consecutive net-inflow days, (2) 5-day cumulative net flow as % of sector market cap. High momentum = sustained institutional accumulation signal.

## 大资金动向 (Big Money Flow)

A standalone page (separate from 板块资金流) tracking institutional-scale capital flows that can move the A-share market. Two primary signals: 北向资金 (foreign smart money direction) and 国家队ETF份额 (inferred state intervention). Also shows a 底部信号 score in Phase B.

## 北向资金 (Northbound Capital)

Foreign capital flowing into A-shares via 沪深港通 (Stock Connect). Represents overseas institutional investors. Tends to exit before major downturns and re-enter at bottoms. Tracked via daily net buy amount (成交净买额). Does NOT represent 国家队 — these are distinct entities with different motivations.

## 国家队 (National Team)

Domestic Chinese state-backed investment vehicles that intervene to stabilize markets: primarily 中央汇金 (Central Huijin) and 证金公司 (China Securities Finance). Mandate is market stability, not profit. Buys during crashes; no real-time disclosure. Inferred indirectly via ETF 份额异动 for 510050 / 510300 / 510500.

## 中央汇金 (Central Huijin)

The principal 国家队 entity. Intervenes by purchasing large-cap ETFs on the secondary market (场内). Known public interventions: Oct 2023 and Feb 2024. Activity inferred from 基金份额 spikes in 510050, 510300, 510500 — not directly observable in real time.

## 底部信号 (Bottom Signal)

A composite 0–100 score estimating the probability of a near-term market bottom. Phase B feature. Inputs: consecutive northbound outflow days + ETF share spike detection (vs 20-day average) + market decline from recent high. Used for observation and validation, not as a trading trigger.

## 基金份额异动 (ETF Share Spike)

A Z-score-based detection of abnormal increases in total ETF units outstanding for 510050 / 510300 / 510500. A spike (>2σ above 20-day average daily change) is treated as a 国家队 buy signal. Only detectable via primary-market (场外申购) activity — secondary market purchases by 汇金 are not reflected in share counts.

## 大类资产组合回测 (Portfolio Backtest)

A standalone page for backtesting multi-asset portfolios against historical Chinese ETF price data. Supports preset scenario configurations and fully custom portfolio builder. Backtest period covers from ~2013 (earliest common start date across all 5 supported ETFs) to present.

## 资产宇宙 (Asset Universe)

The fixed set of 5 Chinese ETFs available for portfolio construction in the backtest system:

| 类别 | ETF | 代码 | 数据起点 |
|------|-----|------|---------|
| A股大盘 | 沪深300 ETF | 510300 | 2012 |
| A股蓝筹 | 上证50 ETF | 510050 | 2004 |
| A股成长 | 创业板100 ETF | 159915 | 2010 |
| 中债 | 国债 ETF | 511010 | 2013 |
| 黄金 | 黄金 ETF 华安 | 518880 | 2013 |

No US stocks or REITs (公募REITs launched 2021, too short for meaningful backtest).

## 定期再平衡 (Periodic Rebalancing)

The rebalancing strategy used in the backtest: at each rebalancing date (end of month for 1M, end of quarter for 1Q), holdings are forcibly reset to target weights regardless of market movement. A sell-high-buy-low mechanical discipline. Does not use market signals or timing indicators.

## 预设场景 (Preset Scenarios)

Five built-in portfolio configurations available as starting points:

- **股债平衡**: 510300 60% + 511010 40% — classic 60/40
- **全天候（中国版）**: 510300 30% + 511010 40% + 518880 15% + 159915 15% — Bridgewater All Weather adapted for China
- **永久组合**: 510300 25% + 510050 25% + 511010 25% + 518880 25% — Harry Browne Permanent Portfolio
- **科技成长**: 159915 60% + 510300 20% + 511010 20% — growth-tilted
- **红利稳健**: 510050 50% + 511010 30% + 518880 20% — defensive blue-chip

## 回测指标 (Backtest Metrics)

The four output metrics computed for each backtest run: 年化收益率 (annualized return), 最大回撤 (maximum drawdown), 夏普比率 (Sharpe ratio), and 累计净值曲线 (cumulative NAV curve). The NAV curve also overlays key market event annotations (e.g., 沪深300 MA200 crossings) to provide context for drawdown periods.
