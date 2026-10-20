"""阶段一明确支持的指标，不推测未知字段或会计口径。"""

SYNTHETIC_NOTICE = "模拟数据，仅用于功能演示"
BASE_METRICS = {
    "sales_amount": ("currency", "样本销售额"),
    "orders_count": ("count", "有效订单数"),
    "active_customers": ("count", "期间活跃客户数"),
    "net_profit": ("currency", "净利润"),
}
DERIVED_METRICS = {
    "average_order_value": ("currency/order", "sales_amount / orders_count"),
    "sales_period_growth": ("ratio", "sales_amount / previous_period(sales_amount) - 1"),
    "sales_yoy": ("ratio", "sales_amount / previous_year(sales_amount) - 1"),
    "sales_change": ("currency", "sales_amount - previous_period(sales_amount)"),
    "sales_yoy_change": ("currency", "sales_amount - previous_year(sales_amount)"),
    "profit_change": ("currency", "net_profit - previous_period(net_profit)"),
}
INPUT_COLUMNS = [
    "case_id",
    "metric_id",
    "value",
    "unit",
    "currency",
    "period_start",
    "period_end",
    "frequency",
    "definition",
    "source_record_id",
    "status",
    "missing_reason",
]
OUTPUT_COLUMNS = INPUT_COLUMNS + ["formula", "inputs", "data_type", "data_notice"]
KEY = ["case_id", "metric_id", "period_start"]


class DataError(ValueError):
    """输入或快照不符合已声明的数据契约。"""
