"""
Goal-Driven Trading OS — Alert System
飞书 Webhook + Twilio SMS 双渠道告警
"""
import os
import json
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from models import AlertConfig, AlertHistory, Position, UserGoals

logger = logging.getLogger(__name__)


def send_feishu_alert(webhook_url: str, title: str, body: str, level: str = "warning") -> bool:
    """发送飞书 Webhook 消息"""
    if not webhook_url:
        return False

    try:
        import httpx
        color = "red" if level == "critical" else "orange" if level == "warning" else "blue"
        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": f"⚠ {title}"},
                    "template": color,
                },
                "elements": [
                    {"tag": "div", "text": {"tag": "plain_text", "content": body}},
                ],
            },
        }
        resp = httpx.post(webhook_url, json=payload, timeout=10)
        return resp.status_code == 200
    except ImportError:
        logger.error("httpx not installed, cannot send Feishu alert")
        return False
    except Exception as e:
        logger.error(f"Feishu alert failed: {e}")
        return False


def send_sms_alert(to_phone: str, body: str) -> bool:
    """发送 Twilio 短信"""
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_FROM_NUMBER")

    if not all([account_sid, auth_token, from_number, to_phone]):
        return False

    try:
        from twilio.rest import Client
        client = Client(account_sid, auth_token)
        message = client.messages.create(body=body, from_=from_number, to=to_phone)
        return message.sid is not None
    except ImportError:
        logger.error("twilio not installed, cannot send SMS")
        return False
    except Exception as e:
        logger.error(f"SMS alert failed: {e}")
        return False


def send_alert(db: Session, alert_type: str, title: str, body: str, position_id: int = None) -> dict:
    """
    发送告警 (带频率限制)

    Returns: {delivered, channel, message}
    """
    config = db.query(AlertConfig).first()
    if not config or not config.is_active:
        return {"delivered": False, "message": "告警未配置或已禁用"}

    # Rate limiting
    cutoff = datetime.utcnow() - timedelta(minutes=config.rate_limit_minutes)
    recent = db.query(AlertHistory).filter(
        AlertHistory.alert_type == alert_type,
        AlertHistory.created_at > cutoff,
    )
    if position_id:
        recent = recent.filter(AlertHistory.position_id == position_id)

    if recent.first():
        history = AlertHistory(
            alert_type=alert_type, title=title, body=body,
            position_id=position_id, channel="none",
            was_rate_limited=True, delivered=False,
        )
        db.add(history)
        db.commit()
        return {"delivered": False, "message": f"频率限制中 (每 {config.rate_limit_minutes} 分钟一次)"}

    # Send via configured channels
    feishu_ok = send_feishu_alert(config.feishu_webhook_url, title, body) if config.feishu_webhook_url else False
    sms_ok = send_sms_alert(config.sms_phone, f"{title}\n{body}") if config.sms_enabled else False

    channel = "both" if feishu_ok and sms_ok else "feishu" if feishu_ok else "sms" if sms_ok else "none"
    delivered = feishu_ok or sms_ok

    history = AlertHistory(
        alert_type=alert_type, title=title, body=body,
        position_id=position_id, channel=channel,
        was_rate_limited=False, delivered=delivered,
    )
    db.add(history)
    db.commit()

    return {"delivered": delivered, "channel": channel, "message": f"告警已发送 ({channel})"}


def check_and_fire_alerts(db: Session) -> list[dict]:
    """
    检查所有告警条件并触发

    Returns: 触发的告警列表
    """
    config = db.query(AlertConfig).first()
    if not config or not config.is_active:
        return []

    goals = db.query(UserGoals).first()
    positions = db.query(Position).filter(Position.is_open == True).all()
    fired = []

    if not positions:
        return fired

    # 1. 总回撤检查
    total_unrealized = sum(p.unrealized_pnl or 0 for p in positions)
    total_value = positions[0].account_balance_at_entry or 10000 if positions else 10000

    if total_value > 0 and total_unrealized < 0:
        drawdown = abs(total_unrealized) / total_value

        if drawdown >= config.drawdown_critical_pct:
            result = send_alert(db, "drawdown_critical",
                f"严重回撤警告: {drawdown*100:.1f}%",
                f"当前组合未实现亏损 ${abs(total_unrealized):.2f}，回撤 {drawdown*100:.1f}%，超过临界线 {config.drawdown_critical_pct*100:.1f}%。建议立即减仓。")
            fired.append(result)

        elif drawdown >= config.drawdown_warn_pct:
            result = send_alert(db, "drawdown_warning",
                f"回撤预警: {drawdown*100:.1f}%",
                f"当前回撤 {drawdown*100:.1f}%，接近你的上限 {goals.max_drawdown*100:.1f}%。请注意风险。" if goals else f"当前回撤 {drawdown*100:.1f}%")
            fired.append(result)

    # 2. 单仓位亏损检查
    for p in positions:
        if p.unrealized_pnl and p.unrealized_pnl < 0:
            position_value = (p.entry_price or 1) * (p.quantity or 1)
            loss_pct = abs(p.unrealized_pnl) / position_value if position_value > 0 else 0

            if loss_pct >= config.single_position_loss_pct:
                result = send_alert(db, "position_loss",
                    f"{p.symbol} 亏损 {loss_pct*100:.1f}%",
                    f"{p.symbol} 未实现亏损 ${abs(p.unrealized_pnl):.2f} ({loss_pct*100:.1f}%)，超过单仓位告警阈值 {config.single_position_loss_pct*100:.1f}%。",
                    position_id=p.id)
                fired.append(result)

    # 3. VIX 异常检查
    from market_data import fetch_vix
    try:
        vix_data = fetch_vix()
        vix = vix_data.get("price", 0)
        if vix >= config.vix_spike_threshold:
            result = send_alert(db, "vix_spike",
                f"VIX 飙升: {vix:.1f}",
                f"VIX 当前 {vix:.1f}，超过告警阈值 {config.vix_spike_threshold:.0f}。市场恐慌情绪升高，请检查持仓。")
            fired.append(result)
    except Exception:
        pass

    return fired
