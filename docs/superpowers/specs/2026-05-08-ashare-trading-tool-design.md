# A股自动化交易工具 — 设计文档

> 创建日期: 2026-05-08
> 状态: 设计中

## 1. 项目概述

个人研究用 A 股桌面交易工具，支持数据下载、策略设计、回测分析、参数优化与市场情绪分析。策略风格为技术面择时 + 基本面选股的混合型。

## 2. 架构

```
Electron UI ←→ REST API (localhost:8765) ←→ Python FastAPI 后端
                                                ├── 数据模块 (AKShare/BaoStock)
                                                ├── 存储模块 (SQLite + Parquet)
                                                ├── 策略引擎
                                                ├── 回测引擎
                                                ├── 参数优化 (Optuna)
                                                └── 情绪分析模块
```

- 前端: Electron (沿用现有骨架), 通过 HTTP 与后端通信
- 后端: Python 3.11 + FastAPI, 独立进程, 前端启动时自动拉起

## 3. 目录结构

```
claude01/
├── backend/
│   ├── main.py            # FastAPI 入口, 生命周期管理
│   ├── config.py           # 配置加载
│   ├── api/                # 路由层
│   │   ├── data.py         # 数据相关接口
│   │   ├── strategy.py     # 策略管理接口
│   │   ├── backtest.py     # 回测接口
│   │   └── sentiment.py    # 情绪分析接口
│   ├── services/           # 业务逻辑层
│   │   ├── data_service.py
│   │   ├── strategy_service.py
│   │   ├── backtest_service.py
│   │   └── sentiment_service.py
│   ├── engine/             # 核心引擎
│   │   ├── strategy.py     # 策略基类
│   │   ├── indicators.py   # 指标库 (MA/MACD/RSI/布林/ATR)
│   │   ├── backtest.py     # 回测引擎 (日线/分钟, 手续费/滑点/印花税/T+1)
│   │   ├── optimizer.py    # Optuna 参数优化
│   │   └── sentiment.py    # 市场情绪评分引擎
│   └── storage/            # 数据持久化
│       ├── db.py           # SQLite 连接管理
│       ├── fetcher.py      # AKShare/BaoStock 数据下载
│       └── cleaner.py      # 清洗/去重/前复权/停牌标记
├── frontend/               # 现有 Electron 代码收拢至此
├── data/                   # 本地数据存储目录
│   ├── raw/                # 原始下载数据
│   ├── cleaned/            # 清洗后 Parquet
│   └── cache/              # 策略用缓存快照
└── config.yaml             # 全局配置 (数据源/路径/端口)
```

## 4. 数据管线

### 4.1 数据源

| 数据类型 | 来源 | 频率 | 存储 |
|---------|------|------|------|
| 日线行情 (OHLCV) | AKShare/BaoStock | 日 | Parquet |
| 分钟行情 | AKShare | 1分/5分 | Parquet |
| 财务数据 (三表) | AKShare | 季/年 | Parquet |
| 龙虎榜 | AKShare | 日 | Parquet |
| 行业分类 | AKShare | 静态 | JSON |
| 资金流 | AKShare | 日 | Parquet |
| 融资融券 | AKShare | 日 | Parquet |

### 4.2 数据流程

fetcher.py → cleaner.py → Parquet/SQLite → Service Layer

- **增量更新**: 按 symbol+日期查最新记录, 只拉增量部分
- **数据校验**: 去重、OHLC 合理性检查、停牌日期标记
- **缓存分层**: raw/ → cleaned/ → cache/, 逐层处理, 上游不改下游
- **限速保护**: AKShare 免费接口 asyncio.Semaphore 控制并发
- **容灾**: 主源失败自动切备源, 指数退避重试

### 4.3 对外 API

```
GET  /api/data/stocks                    # 股票列表 + 行业
GET  /api/data/daily/{symbol}?start=&end=  # 日线数据
GET  /api/data/financials/{symbol}       # 财务数据
POST /api/data/download                  # 触发下载任务
GET  /api/data/download/status/{task_id} # 下载进度
```

## 5. 策略引擎

### 5.1 策略定义

类继承 + 配置驱动。用户只需实现:

```python
class BaseStrategy(ABC):
    def init(self, data: pd.DataFrame): pass       # 一次性指标计算
    def next(self, i: int, bar: dict) -> Signal | None: pass  # 每 bar 调用
```

Signal 结构: symbol, action(BUY/SELL), size, price_type, limit_price

### 5.2 内置指标库

`engine/indicators.py` — MA, MACD, RSI, 布林带, ATR, 成交量分布

### 5.3 组合管理

- T+1 卖出限制: 当日买入次日才能卖
- 涨跌停约束: 涨停不买, 跌停不卖
- 仓位/资金管理: 单票仓位上限, 总仓位上限

### 5.4 API

```
GET  /api/strategy/templates              # 预置策略模板列表
POST /api/strategy/create                  # 创建/编辑策略
POST /api/strategy/validate                # 验证策略逻辑正确性
```

## 6. 回测引擎

### 6.1 核心类

```python
class BacktestEngine:
    def run(strategy_cls, start_date, end_date,
            universe: list[str],
            initial_cash=100000, benchmark='000300') -> BacktestResult
```

### 6.2 输出指标

total_return, annual_return, max_drawdown, sharpe_ratio, win_rate,
profit_loss_ratio, daily_pnl, trades, benchmark_compare

### 6.3 API

```
POST /api/backtest/run              # 执行回测
GET  /api/backtest/result/{id}      # 回测结果 + 权益曲线
GET  /api/backtest/trades/{id}      # 逐笔交易明细
```

## 7. 参数优化

- 引擎: Optuna (贝叶斯优化)
- 数据切分: 训练/验证/测试按时间顺序 → 防过拟合
- 输出: 最优参数 + 参数稳定性报告 (±10% 扰动检验)

```
POST /api/optimize/run               # 启动优化任务
GET  /api/optimize/result/{id}       # 优化结果 + 参数重要性
```

## 8. 市场情绪

5 因子加权求和, 标准化到 0-100:
- 资金流方向 (20%)
- 龙虎榜活跃度 (20%)
- 涨跌停家数比 (20%)
- 成交额偏离度 (20%)
- 融资融券余额变化 (20%)

```
GET /api/sentiment?start=&end=         # 历史情绪指数
GET /api/sentiment/current             # 当前情绪快照
```

## 9. 全局异常处理

- API 异常统一格式: `{"error": "CODE", "detail": "message"}`
- 数据源失败: 自动切换备源
- 接口限流: 429 → 指数退避 (1s→2s→4s→...→max 60s)
- 日志: loguru, 按日滚存, 保留 30 天

## 10. 构建顺序

按依赖关系, 分 4 阶段:

| 阶段 | 内容 | 依赖 |
|------|------|------|
| Phase 1 | 数据管线 (下载/清洗/存储/API) | 无 |
| Phase 2 | 策略引擎 + 回测引擎 | Phase 1 |
| Phase 3 | 参数优化 + 市场情绪 | Phase 2 |
| Phase 4 | 前端集成 (数据面板/回测图表/策略编辑) | Phase 3 |
