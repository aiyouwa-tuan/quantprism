"""
预置策略种子数据
系统首次启动时自动创建，用户可以在网页上修改
"""
import json


DEFAULT_STRATEGIES = [
    {
        "strategy_name": "m7_leaps",
        "display_name": "M7 LEAPS (左侧抄底)",
        "description": "大科技股（M7）在超卖时买入长期看涨期权 delta 0.7。VIX 15-25 + RSI<=40 + 布林带下轨触发。止盈阶梯: 7天10% / 4周20% / 翻倍止盈 / 到期前90天强平。",
        "symbol": "M7",
        "symbol_pool": "AAPL,MSFT,GOOGL,AMZN,NVDA,META,TSLA",
        "strategy_type": "entry",
        "direction": "bullish",
        "instrument": "call",
        "params_yaml": json.dumps({
            "vix_min": 15, "vix_max": 25,
            "rsi_threshold": 40,
            "delta_target": 0.7,
            "max_position_pct": 0.20,
            "profit_7d": 0.10, "profit_4w": 0.20, "profit_strong": 1.0,
            "force_close_dte": 90,
        }, ensure_ascii=False),
    },
    {
        "strategy_name": "m7_covered_call",
        "display_name": "M7 Covered Call (上涨收租)",
        "description": "持有正股盈利时，在上涨乏力 / 阻力位卖出 Call 收权利金。RSI > 70 + 布林带上轨触发。30-45 天到期。不卖核心资产，只卖波段资产。",
        "symbol": "M7",
        "symbol_pool": "AAPL,MSFT,GOOGL,AMZN,NVDA,META,TSLA",
        "strategy_type": "exit",
        "direction": "neutral",
        "instrument": "covered_call",
        "params_yaml": json.dumps({
            "rsi_threshold": 70,
            "dte_target": 30, "dte_max": 45,
            "otm_pct": 0.05,
        }),
    },
    {
        "strategy_name": "tqqq_dip",
        "display_name": "TQQQ 抄底 (杠杆低吸)",
        "description": "QQQ 在 MA200 上方 4%+ 且单日回调 > 1% 时买入 TQQQ。仓位 20%。出仓: QQQ 跌破 MA200 下方 3% 全部清仓。",
        "symbol": "TQQQ",
        "symbol_pool": "QQQ,TQQQ",
        "strategy_type": "entry",
        "direction": "bullish",
        "instrument": "stock",
        "params_yaml": json.dumps({
            "sma_200_above_pct": 0.04,
            "daily_dip_pct": -0.01,
            "position_pct": 0.20,
            "exit_below_sma200_pct": -0.03,
        }),
    },
    {
        "strategy_name": "qqq_leaps",
        "display_name": "QQQ LEAPS (长期看涨)",
        "description": "QQQ 日跌 1% 时买入一年期看涨期权 delta 0.6。单次 20% 仓位，上限 5 笔。止盈阶梯: 0-4月>50% / 4-6月>30% / 7-9月>10% / >9月强平。",
        "symbol": "QQQ",
        "symbol_pool": "QQQ",
        "strategy_type": "entry",
        "direction": "bullish",
        "instrument": "call",
        "params_yaml": json.dumps({
            "dip_threshold": -0.01,
            "delta_target": 0.6,
            "position_pct": 0.20,
            "max_positions": 5,
            "dte_target": 365,
            "profit_0_4m": 0.50, "profit_4_6m": 0.30, "profit_7_9m": 0.10,
            "force_close_months": 9,
        }),
    },
    {
        "strategy_name": "waiting_strike",
        "display_name": "待击球 (左侧抄底)",
        "description": "寻找市场极度恐慌、技术面严重超卖的错杀机会。RSI <= 40 + 布林带下轨同时触发时，分批建仓。",
        "symbol": "ALL",
        "symbol_pool": "AAPL,MSFT,GOOGL,AMZN,NVDA,META,TSLA,AMD,TSM",
        "strategy_type": "entry",
        "direction": "bullish",
        "instrument": "stock",
        "params_yaml": json.dumps({
            "rsi_threshold": 40,
            "stop_loss_atr_mult": 2.0,
        }),
    },
    {
        "strategy_name": "dip_watch",
        "display_name": "回马枪 (顺势低吸)",
        "description": "趋势确立背景下，强势标的健康回调。RSI 45-55 中性区 + 回踩 MA10/MA20 触发，顺势加仓。",
        "symbol": "ALL",
        "symbol_pool": "AAPL,MSFT,GOOGL,AMZN,NVDA,META,TSLA,AMD,TSM",
        "strategy_type": "entry",
        "direction": "bullish",
        "instrument": "stock",
        "params_yaml": json.dumps({
            "rsi_low": 45, "rsi_high": 55,
            "ma_touch_tolerance": 0.005,
            "stop_loss_atr_mult": 1.5,
        }),
    },
    {
        "strategy_name": "top_prediction",
        "display_name": "顶部预测 (右侧止盈)",
        "description": "识别上涨动能衰竭。4 个见顶信号中任意 2 个触发即警报: (1)缩量逼近前高 (2)长上影线/阴包阳 (3)跌破MA5 (4)MACD顶背离。",
        "symbol": "ALL",
        "symbol_pool": "AAPL,MSFT,GOOGL,AMZN,NVDA,META,TSLA,AMD,TSM,QQQ",
        "strategy_type": "exit",
        "direction": "bearish",
        "instrument": "stock",
        "params_yaml": json.dumps({
            "signals_needed": 2,
            "volume_shrink_pct": 0.7,
            "upper_shadow_ratio": 2.0,
        }),
    },
    {
        "strategy_name": "sell_put_conservative",
        "display_name": "稳健 Sell Put (收租型)",
        "description": "选择支撑位明确、安全边际充足的标的卖出 Put 收权利金。DTE 30-45天，Delta -0.15~-0.05。",
        "symbol": "ALL",
        "symbol_pool": "AAPL,MSFT,GOOGL,AMZN,NVDA,META,SPY,QQQ",
        "strategy_type": "entry",
        "direction": "neutral",
        "instrument": "sell_put",
        "params_yaml": json.dumps({
            "dte_min": 30, "dte_max": 45,
            "delta_min": -0.25, "delta_max": -0.05,
            "min_safety_margin": 0.05,
            "min_iv_rank": 30,
            "max_position_pct": 0.05,
            "max_sector_exposure": 0.25,
            "profit_target": 0.50,
            "stop_loss_pct": -1.50,
            "time_stop_days": 14,
        }),
    },
    {
        "strategy_name": "sma_crossover",
        "display_name": "SMA 双均线交叉",
        "description": "快速均线上穿慢速均线买入，下穿卖出。适合趋势市场。默认 20/50 日均线。",
        "symbol": "SPY",
        "symbol_pool": "SPY,QQQ,IWM",
        "strategy_type": "entry",
        "direction": "bullish",
        "instrument": "stock",
        "params_yaml": json.dumps({
            "fast_period": 20, "slow_period": 50,
            "stop_loss_atr_mult": 2.0,
        }),
    },
    {
        "strategy_name": "bollinger_reversion",
        "display_name": "布林带均值回归",
        "description": "价格触碰布林带下轨买入，回到中轨卖出。利用价格回归均值的特性。",
        "symbol": "SPY",
        "symbol_pool": "SPY,QQQ,IWM",
        "strategy_type": "entry",
        "direction": "bullish",
        "instrument": "stock",
        "params_yaml": json.dumps({
            "bb_period": 20, "bb_std": 2.0,
            "stop_loss_atr_mult": 1.5,
            "exit_at": "mid",
        }),
    },
]


def seed_strategies(db):
    """首次启动时预置策略到数据库"""
    from models import StrategyConfig

    existing = db.query(StrategyConfig).count()
    if existing > 0:
        return  # 已有数据，不覆盖

    for s in DEFAULT_STRATEGIES:
        config = StrategyConfig(
            strategy_name=s["strategy_name"],
            display_name=s["display_name"],
            description=s["description"],
            symbol=s["symbol"],
            symbol_pool=s.get("symbol_pool"),
            strategy_type=s.get("strategy_type", "custom"),
            direction=s.get("direction", "bullish"),
            instrument=s.get("instrument", "stock"),
            params_yaml=s["params_yaml"],
            is_active=True,
            is_default=True,
        )
        db.add(config)

    db.commit()
