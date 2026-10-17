import structlog

logger = structlog.get_logger("motionile.alerts")


def raise_alert(code: str, **fields: object) -> None:
    logger.critical("alert.raised", alert=True, alert_code=code, **fields)
