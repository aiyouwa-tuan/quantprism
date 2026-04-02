"""
Goal-Driven Trading OS — Scheduler
定时任务：每日扫描 + 信号生成 + 风控检查 + 飞书推送

使用 APScheduler，随 FastAPI 启动/停止
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# APScheduler 可选依赖
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False
    logger.warning("APScheduler not installed. 定时任务不可用。pip install apscheduler")

scheduler = None


def _get_db():
    """获取数据库 session（在定时任务上下文中）"""
    from models import get_db
    return next(get_db())


def job_daily_scan():
    """
    每日扫描任务（美东 9:35 触发）
    1. 扫描所有启用的板块
    2. 生成信号
    3. 推送飞书
    """
    logger.info("[Scheduler] 开始每日扫描...")
    db = _get_db()

    try:
        from models import StrategyConfig, UserGoals
        from opportunity_engine import find_opportunities
        from stock_screener import SECTORS
        import json

        goals = db.query(UserGoals).first()
        active_configs = db.query(StrategyConfig).filter(StrategyConfig.is_active == True).all()
        strategy_configs = [
            {
                "id": cfg.id,
                "strategy_name": cfg.strategy_name,
                "display_name": cfg.display_name or cfg.strategy_name,
                "instrument": cfg.instrument,
                "direction": cfg.direction or "neutral",
                "params": json.loads(cfg.params_yaml or "{}"),
            }
            for cfg in active_configs
        ]

        all_opps = []
        for sector_key in ["TECH", "FINANCE", "HEALTH"]:
            opps = find_opportunities(
                goals_return=goals.annual_return_target if goals else 0.15,
                goals_drawdown=goals.max_drawdown if goals else 0.10,
                risk_per_trade=goals.risk_per_trade if goals else 0.02,
                account_balance=100000,
                sectors=[sector_key],
                strategy_configs=strategy_configs if strategy_configs else None,
            )
            all_opps.extend(opps.get("opportunities", []))

        # 信号生成
        from execution import generate_pending_signals
        signal_count = generate_pending_signals(db)

        # 推送飞书
        if all_opps or signal_count > 0:
            _push_daily_summary(db, all_opps, signal_count)

        logger.info(f"[Scheduler] 扫描完成: {len(all_opps)} 个机会, {signal_count} 个信号")

    except Exception as e:
        logger.error(f"[Scheduler] 每日扫描失败: {e}")
    finally:
        db.close()


def job_risk_check():
    """
    风控检查（每 5 分钟）
    检查持仓风险，触发告警
    """
    db = _get_db()
    try:
        from alerts import check_and_fire_alerts
        fired = check_and_fire_alerts(db)
        if fired:
            logger.info(f"[Scheduler] 风控检查触发 {len(fired)} 条告警")
    except Exception as e:
        logger.error(f"[Scheduler] 风控检查失败: {e}")
    finally:
        db.close()


def _push_daily_summary(db, opportunities, signal_count):
    """推送每日摘要到飞书"""
    try:
        from alerts import send_alert
        top_opps = sorted(opportunities, key=lambda x: x.score, reverse=True)[:5]

        lines = [f"今日扫描发现 {len(opportunities)} 个机会, 生成 {signal_count} 个信号"]
        for opp in top_opps:
            lines.append(f"  {opp.symbol} | 评分 {opp.score} | {opp.strategy} | {opp.recommendation}")

        content = "\n".join(lines)
        send_alert(db, "daily_scan", "每日扫描摘要", content)
    except Exception as e:
        logger.error(f"[Scheduler] 飞书推送失败: {e}")


def init_scheduler():
    """初始化定时任务调度器"""
    global scheduler

    if not HAS_APSCHEDULER:
        logger.warning("APScheduler 未安装，跳过定时任务初始化")
        return

    scheduler = BackgroundScheduler(timezone="US/Eastern")

    # 每日扫描：美东时间 9:35（开盘后 5 分钟）
    scheduler.add_job(
        job_daily_scan, CronTrigger(hour=9, minute=35),
        id="daily_scan", name="每日机会扫描",
        replace_existing=True, misfire_grace_time=3600,
    )

    # 风控检查：美股交易时段每 5 分钟（9:30-16:00 ET）
    scheduler.add_job(
        job_risk_check, CronTrigger(minute="*/5", hour="9-16"),
        id="risk_check", name="风控检查",
        replace_existing=True, misfire_grace_time=300,
    )

    scheduler.start()
    logger.info("[Scheduler] 定时任务已启动: 每日扫描(9:35 ET) + 风控检查(每5分钟)")


def shutdown_scheduler():
    """关闭调度器"""
    global scheduler
    if scheduler:
        scheduler.shutdown(wait=False)
        logger.info("[Scheduler] 定时任务已停止")


def get_scheduler_status() -> dict:
    """获取调度器状态"""
    if not HAS_APSCHEDULER:
        return {"status": "unavailable", "message": "APScheduler 未安装", "jobs": []}

    if scheduler is None:
        return {"status": "stopped", "jobs": []}

    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": str(job.next_run_time) if job.next_run_time else "N/A",
            "trigger": str(job.trigger),
        })

    return {
        "status": "running" if scheduler.running else "stopped",
        "jobs": jobs,
    }
