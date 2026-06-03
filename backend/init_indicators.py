"""Initialize default indicator templates."""
from sqlalchemy.orm import Session
from app.core.database import SessionLocal, engine, Base
from app.models.indicator import IndicatorTemplate


def init_indicator_templates(db: Session):
    """Initialize default indicator templates."""
    
    templates = [
        {
            "id": "MA200",
            "name": "200周均线偏离度",
            "description": "计算价格相对于200周均线的偏离百分比，用于判断超长期趋势和估值水平（过滤短期噪音）",
            "indicator_type": "metric",
            "category": "trend",
            "processor_class": "MA200",
            "default_params": {
                "period": 200,
                "price_field": "close"
            },
            "output_fields": [
                {"name": "value", "type": "float", "description": "偏离百分比 (%)"},
                {"name": "value_text", "type": "string", "description": "文本描述", "optional": True},
                {"name": "grade", "type": "string", "description": "档位", "optional": True},
                {"name": "grade_label", "type": "string", "description": "档位标签", "optional": True},
                {"name": "ma_value", "type": "float", "description": "200周均线值", "optional": True},
                {"name": "current_price", "type": "float", "description": "当前价格", "optional": True},
            ],
            "grading_config": {
                "grades": [
                    {"grade": "very_low", "min": float('-inf'), "max": -50, "label": "极度低估"},
                    {"grade": "low", "min": -50, "max": -25, "label": "低估"},
                    {"grade": "medium_low", "min": -25, "max": -10, "label": "偏低"},
                    {"grade": "medium", "min": -10, "max": 10, "label": "合理"},
                    {"grade": "medium_high", "min": 10, "max": 25, "label": "偏高"},
                    {"grade": "high", "min": 25, "max": 50, "label": "高估"},
                    {"grade": "very_high", "min": 50, "max": float('inf'), "label": "极度高估"},
                ]
            },
            "is_active": True,
        },
        {
            "id": "BTC_FEAR_GREED",
            "name": "BTC恐慌贪婪指数",
            "description": "Alternative.me BTC Fear & Greed Index，反映市场情绪",
            "indicator_type": "sentiment",
            "category": "sentiment",
            "processor_class": "BTC_FEAR_GREED",
            "default_params": {
                "api_url": "https://api.alternative.me/fng/"
            },
            "output_fields": [
                {"name": "value", "type": "float", "description": "指数值 (0-100)"},
                {"name": "value_text", "type": "string", "description": "情绪描述"},
                {"name": "grade", "type": "string", "description": "档位", "optional": True},
                {"name": "grade_label", "type": "string", "description": "档位标签", "optional": True},
            ],
            "grading_config": {
                "grades": [
                    {"grade": "extreme_fear", "min": 0, "max": 25, "label": "极度恐惧"},
                    {"grade": "fear", "min": 25, "max": 50, "label": "恐惧"},
                    {"grade": "neutral", "min": 46, "max": 55, "label": "中性"},
                    {"grade": "greed", "min": 50, "max": 75, "label": "贪婪"},
                    {"grade": "extreme_greed", "min": 75, "max": 100, "label": "极度贪婪"},
                ]
            },
            "is_active": True,
        },
        {
            "id": "CNN_FEAR_GREED",
            "name": "美股恐慌贪婪指数CNN",
            "description": "CNN Fear & Greed Index，基于美股市场综合情绪指标。数据源：github.com/whit3rabbit/fear-greed-data",
            "indicator_type": "sentiment",
            "category": "sentiment",
            "processor_class": "CNN_FEAR_GREED",
            "default_params": {
                "csv_url": "https://raw.githubusercontent.com/whit3rabbit/fear-greed-data/main/fear-greed.csv"
            },
            "output_fields": [
                {"name": "value", "type": "float", "description": "指数值 (0-100)"},
                {"name": "value_text", "type": "string", "description": "情绪描述"},
                {"name": "grade", "type": "string", "description": "档位", "optional": True},
                {"name": "grade_label", "type": "string", "description": "档位标签", "optional": True},
            ],
            "grading_config": {
                "grades": [
                    {"grade": "extreme_fear", "min": 0, "max": 25, "label": "极度恐惧"},
                    {"grade": "fear", "min": 25, "max": 45, "label": "恐惧"},
                    {"grade": "neutral", "min": 45, "max": 56, "label": "中性"},
                    {"grade": "greed", "min": 56, "max": 75, "label": "贪婪"},
                    {"grade": "extreme_greed", "min": 75, "max": 100, "label": "极度贪婪"},
                ]
            },
            "is_active": True,
        },
        {
            "id": "VIX",
            "name": "标普500波动率指数VIX",
            "description": "CBOE Volatility Index，市场恐慌指数",
            "indicator_type": "volatility",
            "category": "volatility",
            "processor_class": "VIX",
            "default_params": {
                "symbol": "^VIX",
                "threshold_low": 20,
                "threshold_high": 30,
            },
            "output_fields": [
                {"name": "value", "type": "float", "description": "VIX值"},
                {"name": "value_text", "type": "string", "description": "市场状态描述"},
                {"name": "grade", "type": "string", "description": "档位", "optional": True},
                {"name": "grade_label", "type": "string", "description": "档位标签", "optional": True},
            ],
            "grading_config": {
                "grades": [
                    {"grade": "calm", "min": 0, "max": 15, "label": "极度平静"},
                    {"grade": "low", "min": 15, "max": 20, "label": "低波动"},
                    {"grade": "normal", "min": 20, "max": 25, "label": "正常波动"},
                    {"grade": "elevated", "min": 25, "max": 30, "label": "波动加剧"},
                    {"grade": "fear", "min": 30, "max": 40, "label": "市场恐慌"},
                    {"grade": "panic", "min": 40, "max": float('inf'), "label": "极度恐慌"},
                ]
            },
            "is_active": True,
        },
        {
            "id": "VXN",
            "name": "纳斯达克波动率指数VXN",
            "description": "CBOE Nasdaq-100 Volatility Index，科技股恐慌指数",
            "indicator_type": "volatility",
            "category": "volatility",
            "processor_class": "VXN",
            "default_params": {"symbol": "^VXN", "threshold_low": 20, "threshold_high": 30},
            "output_fields": [
                {"name": "value", "type": "float", "description": "VXN值"},
                {"name": "value_text", "type": "string", "description": "市场状态描述"},
                {"name": "grade", "type": "string", "description": "档位", "optional": True},
                {"name": "grade_label", "type": "string", "description": "档位标签", "optional": True},
            ],
            "grading_config": {
                "grades": [
                    {"grade": "calm", "min": 0, "max": 15, "label": "极度平静"},
                    {"grade": "low", "min": 15, "max": 20, "label": "低波动"},
                    {"grade": "normal", "min": 20, "max": 25, "label": "正常波动"},
                    {"grade": "elevated", "min": 25, "max": 30, "label": "波动加剧"},
                    {"grade": "fear", "min": 30, "max": 40, "label": "市场恐慌"},
                    {"grade": "panic", "min": 40, "max": float('inf'), "label": "极度恐慌"},
                ]
            },
            "is_active": True,
        },
        {
            "id": "VXD",
            "name": "道琼斯波动率指数VXD",
            "description": "CBOE DJIA Volatility Index，道指恐慌指数",
            "indicator_type": "volatility",
            "category": "volatility",
            "processor_class": "VXD",
            "default_params": {"symbol": "^VXD", "threshold_low": 18, "threshold_high": 28},
            "output_fields": [
                {"name": "value", "type": "float", "description": "VXD值"},
                {"name": "value_text", "type": "string", "description": "市场状态描述"},
                {"name": "grade", "type": "string", "description": "档位", "optional": True},
                {"name": "grade_label", "type": "string", "description": "档位标签", "optional": True},
            ],
            "grading_config": {
                "grades": [
                    {"grade": "calm", "min": 0, "max": 15, "label": "极度平静"},
                    {"grade": "low", "min": 15, "max": 18, "label": "低波动"},
                    {"grade": "normal", "min": 18, "max": 22, "label": "正常波动"},
                    {"grade": "elevated", "min": 22, "max": 28, "label": "波动加剧"},
                    {"grade": "fear", "min": 28, "max": 38, "label": "市场恐慌"},
                    {"grade": "panic", "min": 38, "max": float('inf'), "label": "极度恐慌"},
                ]
            },
            "is_active": True,
        },

        {
            "id": "OVX",
            "name": "原油波动率指数OVX",
            "description": "CBOE Crude Oil Volatility Index，原油恐慌指数",
            "indicator_type": "volatility",
            "category": "volatility",
            "processor_class": "OVX",
            "default_params": {"symbol": "^OVX", "threshold_low": 35, "threshold_high": 50},
            "output_fields": [
                {"name": "value", "type": "float", "description": "OVX值"},
                {"name": "value_text", "type": "string", "description": "市场状态描述"},
                {"name": "grade", "type": "string", "description": "档位", "optional": True},
                {"name": "grade_label", "type": "string", "description": "档位标签", "optional": True},
            ],
            "grading_config": {
                "grades": [
                    {"grade": "calm", "min": 0, "max": 25, "label": "极度平静"},
                    {"grade": "low", "min": 25, "max": 35, "label": "低波动"},
                    {"grade": "normal", "min": 35, "max": 45, "label": "正常波动"},
                    {"grade": "elevated", "min": 45, "max": 55, "label": "波动加剧"},
                    {"grade": "fear", "min": 55, "max": 75, "label": "市场恐慌"},
                    {"grade": "panic", "min": 75, "max": float('inf'), "label": "极度恐慌"},
                ]
            },
            "is_active": True,
        },
        {
            "id": "RSI",
            "name": "RSI 相对强弱指数",
            "description": "14日相对强弱指数，用于判断短期超买/超卖状态",
            "indicator_type": "sentiment",
            "category": "sentiment",
            "processor_class": "RSI",
            "default_params": {
                "period": 14,
                "price_field": "close",
            },
            "output_fields": [
                {"name": "value", "type": "float", "description": "RSI 值 (0-100)"},
                {"name": "value_text", "type": "string", "description": "文本描述", "optional": True},
                {"name": "grade", "type": "string", "description": "档位", "optional": True},
                {"name": "grade_label", "type": "string", "description": "档位标签", "optional": True},
            ],
            "grading_config": {
                "grades": [
                    {"grade": "extreme_oversold",   "min": 0,   "max": 20,  "label": "极度超卖"},
                    {"grade": "oversold",           "min": 20,  "max": 30,  "label": "超卖"},
                    {"grade": "weak",               "min": 30,  "max": 45,  "label": "偏弱"},
                    {"grade": "neutral",            "min": 45,  "max": 55,  "label": "中性"},
                    {"grade": "strong",             "min": 55,  "max": 70,  "label": "偏强"},
                    {"grade": "overbought",         "min": 70,  "max": 80,  "label": "超买"},
                    {"grade": "extreme_overbought", "min": 80,  "max": 101, "label": "极度超买"},
                ]
            },
            "is_active": True,
        },
        {
            "id": "GVZ",
            "name": "黄金波动率指数GVZ",
            "description": "CBOE Gold Volatility Index，黄金恐慌指数",
            "indicator_type": "volatility",
            "category": "volatility",
            "processor_class": "GVZ",
            "default_params": {"symbol": "^GVZ", "threshold_low": 15, "threshold_high": 20},
            "output_fields": [
                {"name": "value", "type": "float", "description": "GVZ值"},
                {"name": "value_text", "type": "string", "description": "市场状态描述"},
                {"name": "grade", "type": "string", "description": "档位", "optional": True},
                {"name": "grade_label", "type": "string", "description": "档位标签", "optional": True},
            ],
            "grading_config": {
                "grades": [
                    {"grade": "calm", "min": 0, "max": 12, "label": "极度平静"},
                    {"grade": "low", "min": 12, "max": 15, "label": "低波动"},
                    {"grade": "normal", "min": 15, "max": 18, "label": "正常波动"},
                    {"grade": "elevated", "min": 18, "max": 22, "label": "波动加剧"},
                    {"grade": "fear", "min": 22, "max": 28, "label": "市场恐慌"},
                    {"grade": "panic", "min": 28, "max": float('inf'), "label": "极度恐慌"},
                ]
            },
            "is_active": True,
        },
    ]
    
    created_count = 0
    for template_data in templates:
        existing = db.query(IndicatorTemplate).filter(
            IndicatorTemplate.id == template_data["id"]
        ).first()
        
        if not existing:
            template = IndicatorTemplate(**template_data)
            db.add(template)
            created_count += 1
            print(f"Created template: {template_data['id']}")
        else:
            print(f"Template already exists: {template_data['id']}")
    
    db.commit()
    print(f"\nTotal templates created: {created_count}")
    return created_count


def init_database():
    """Initialize database with all tables and default data."""
    # Create all tables
    Base.metadata.create_all(bind=engine)
    print("Database tables created")
    
    # Initialize default templates
    db = SessionLocal()
    try:
        init_indicator_templates(db)
    finally:
        db.close()


if __name__ == "__main__":
    init_database()
