# Vestoria Data Terminal

A-股量化投研终端 —— 集成市场估值、技术指标、板块资金流、大资金追踪与多资产组合回测的一体化数据平台。

## 功能模块

### 投资仪表盘 (Investment Dashboard)
四大市场（A股/港股/黄金/原油）独立评分，两个维度：
- **长期分**：基于当前价格偏离 MA200 的程度，0–100 分，反映宏观趋势健康度
- **每日分**：基于 14日RSI（A股/港股）或波动率倒数（黄金/原油），0–100 分，反映短期情绪

### 板块资金流 (Sector Fund Flow)
A 股行业与概念板块的资金流动追踪：
- **行业板块**：~30 个大类行业，历史净流入存储，支持趋势分析
- **概念板块**：300+ 主题概念，每日热门 Top10
- **明日信号**：资金动量 × 价格动量 × 全局风险的合成预测信号（看多/中性/看空）

### 大资金动向 (Big Money Flow)
机构级别资金流追踪：
- **北向资金**：沪深港通外资净买入方向（外资聪明钱）
- **国家队 ETF 份额**：通过 510050/510300/510500 份额异动推断汇金干预行为
- **底部信号**：北向连续流出天数 + ETF 份额 Z-score + 市场跌幅的合成底部概率评分
- **北证50观察**：把北证50作为风险偏好卫星信号，辅助判断小盘/成长风险偏好是否恢复

### 投资组合回测 (Portfolio Backtest)
多资产历史回测，支持 2013 年至今的中国 ETF 数据：
- 预设场景（纯股、股债、全天候等）
- 完全自定义组合权重
- 支持从当前持仓自动生成「组合 A」，方便和目标配置、降风险配置做对比
- 输出：累计收益、年化收益、最大回撤、夏普比率

### 组合配置中枢 (Portfolio Center)
面向日常基金、黄金、现金仓位管理的稳健慢调仓模块：
- **每日持仓快照**：手动维护基金代码、金额、持有收益、资产桶、现金/货币基金余额；保存后写入本地 SQLite，刷新页面不会丢失
- **资产桶建议**：按目标仓位偏离、可动用现金、单日加仓/减仓上限输出加仓、减仓、清仓或观察信号
- **单基金盘中估值建议**：接入东方财富基金估值接口，用盘中涨跌、持有收益、资产桶动作修正 0-3000 元级别的观察动作
- **行业资金流确认**：主题/商品类基金可自动或手动匹配 A 股行业资金流；下拉框支持搜索，未匹配基金可手动选择板块
- **风控降级**：市场偏弱时加仓会降级为「加仓观察」；减仓采用量化触发，包含反弹减仓、连续弱势升档和杀跌刹车
- **黄金宏观确认**：黄金仓位接入 `GC=F` 金价 20 日均线偏离度 + `DX-Y.NYB` 美元指数 5 日趋势，输出加仓观察/持有确认/减仓观察；黄金操作权限默认保持「人工确认」
- **Claude Code 二次审阅**：可调用本地 `ducc` 做风控审阅，作为公式引擎之外的辅助意见

### 技术指标 (Indicators)
- MA200 偏离度（BTC、沪深300、标普500 等）
- RSI 超买超卖
- BTC 恐慌贪婪指数
- VIX 全球风险情绪

### 自选列表 (Watchlist)
多资产类别自定义追踪：股票、加密货币、大宗商品，支持实时价格与涨跌幅。

---

## 快速启动

### Docker（推荐）

```bash
cp .env.example .env
docker compose up -d --build
```

访问：http://localhost:20261

### 本地开发

```bash
# 后端
cd backend && uv sync
uvicorn app.main:app --reload --port 8000

# 前端
cd frontend && npm install && npm run dev
```

一键启停脚本：

```bash
./start.sh   # 启动前后端
./stop.sh    # 停止所有服务
```

### 换电脑拉代码后

```bash
git pull origin main
cd backend && uv sync
cd ../frontend && npm install
cd .. && ./start.sh
```

首次打开组合配置中枢时，后端会自动创建必要的轻量表结构和宏观资产配置，包括：

- `GC=F`：COMEX Gold Futures，用于黄金 20 日均线偏离度
- `DX-Y.NYB`：US Dollar Index，用于美元指数趋势确认

如果黄金宏观卡片显示「美元指数缺失」或「信号不完整」，先刷新价格数据：

```bash
curl -X POST "http://localhost:8000/api/v1/prices/refresh?asset_ids=GC%3DF&asset_ids=DX-Y.NYB"
```

也可以在自选列表/价格刷新入口手动刷新这两个资产。宏观数据未齐全前，黄金建议会保持「人工确认」，不会自动放大加仓金额。

---

## 技术栈

| 层 | 技术 |
|----|------|
| 前端 | React + TypeScript + Vite + Tailwind CSS |
| 后端 | FastAPI + SQLAlchemy + APScheduler |
| 数据 | AkShare（A股）+ yfinance（美股/大宗） |
| 数据库 | SQLite |
| 部署 | Docker Compose + Nginx |

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATABASE_URL` | sqlite:////app/data/data_terminal.db | 数据库路径 |
| `SCHEDULER_ENABLED` | true | 定时数据采集开关 |
| `PROXY_URL` | (空) | 代理地址（访问境外数据源时使用） |
| `FRONTEND_PORT` | 20261 | 前端端口 |

---

## 项目结构

```
vestoria-data-terminal/
├── backend/
│   ├── app/
│   │   ├── api/v1/          # REST API 路由
│   │   ├── fetchers/        # 数据采集（AkShare / yfinance）
│   │   ├── indicators/      # 指标计算（MA200, RSI 等）
│   │   ├── models/          # 数据库模型
│   │   └── services/        # 业务逻辑（回测引擎、大资金信号、调度器）
│   └── init_indicators.py   # 指标初始化脚本
├── frontend/
│   └── src/
│       ├── pages/           # 各功能页面
│       ├── components/      # 可复用组件
│       └── layouts/         # 页面布局
├── db_scripts/              # 数据库脚本与数据探索
├── docker-compose.yml
├── start.sh / stop.sh
└── CONTEXT.md               # 领域术语与设计决策文档
```
