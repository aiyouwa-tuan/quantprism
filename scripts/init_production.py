"""
Initialize production database with API configs and seed data.
Run from project root: python3.11 scripts/init_production.py
"""
import sys
sys.path.insert(0, "app")

from models import SessionLocal, ApiConfig, UserGoals, init_db

init_db()
db = SessionLocal()

# Clear existing API configs
db.query(ApiConfig).delete()

# Seed API configs
api_configs = [
    {"service_name": "deepseek", "display_name": "DeepSeek (AI 分析, 推荐)",
     "api_key": "sk-5c1295614232484796e7f057e6559375", "api_secret": "", "is_active": True, "status": "已配置"},
    {"service_name": "ccxt_binance", "display_name": "Binance (加密货币)",
     "api_key": "jirufWritZFq 1qAzQaim8t7C3OtOQC ohB212pviM6I5LE3bZqwUkRG71jcIr zaSl",
     "api_secret": "DTQvoTOLdHYjMpEfedjdU4XkXpuubcHeSQp9uPK2fnkGPnVAM97NmUOiKDAB3AUK",
     "is_active": True, "status": "已配置"},
    {"service_name": "ibkr", "display_name": "IBKR 盈透证券 (美股/期权)",
     "api_key": "127.0.0.1", "api_secret": "4001", "is_active": True, "status": "已配置"},
]

for cfg in api_configs:
    db.add(ApiConfig(**cfg))

# Seed default goals if not exist
if not db.query(UserGoals).first():
    db.add(UserGoals(
        annual_return_target=0.15,
        max_drawdown=0.10,
        risk_per_trade=0.02,
        max_positions=5,
        max_position_pct=0.20,
        holding_period="days_weeks",
    ))

db.commit()
print(f"Seeded {len(api_configs)} API configs")
print(f"Goals: {'existing' if db.query(UserGoals).count() > 0 else 'created'}")

# Run strategy seeds (from main.py startup)
from strategy_seeds import seed_strategies
seed_strategies(db)
print(f"Strategy configs seeded")

db.close()
print("Production init complete")
