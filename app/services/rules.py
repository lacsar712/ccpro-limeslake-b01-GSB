"""石灰熟化池业务规则。"""

from __future__ import annotations

from app.models import Pond, SlakeBatch

MIN_PEAK_TEMP_FOR_DRAWN = 60.0
# 峰值相对本班目标温偏低超过该度数（℃）即提示告警；仅提示，不挡出灰。
PEAK_TARGET_ALERT_GAP = 15.0


class RuleError(ValueError):
    """业务规则校验失败。"""


def latest_batch_for_pond(pond: Pond) -> SlakeBatch | None:
    if not pond.batches:
        return None
    return max(pond.batches, key=lambda b: b.started_at)


def peak_target_gap(batch: SlakeBatch | None) -> float | None:
    """峰值相对目标温的偏低度数（目标 - 峰值）；峰值未填返回 None。"""
    if batch is None or batch.peak_temp_c is None:
        return None
    return batch.target_temp_c - batch.peak_temp_c


def batch_is_peak_alert(batch: SlakeBatch | None) -> bool:
    """
    峰值偏离告警口径：峰值已填，且比该班目标温低超过 15℃。
    边界（恰好低 15℃）不告警。
    """
    gap = peak_target_gap(batch)
    return gap is not None and gap > PEAK_TARGET_ALERT_GAP


def pond_peak_alert_batch(pond: Pond) -> SlakeBatch | None:
    """
    取该池的告警批次：池须为「熟化中」，且最近班峰值相对目标温偏低超过 15℃。
    其余状态（注水/已出灰）一律不告警，返回 None。
    """
    if pond.status != Pond.STATUS_SLAKING:
        return None
    latest = latest_batch_for_pond(pond)
    return latest if batch_is_peak_alert(latest) else None


def can_mark_pond_drawn(pond: Pond) -> tuple[bool, str]:
    """
    熟化池转为「已出灰」(drawn) 的前提：
    最近一条熟化批次的峰值温度已记录，且 >= 60℃。
    """
    latest = latest_batch_for_pond(pond)
    if latest is None:
        return False, "该池尚无熟化批次，不能标记为已出灰"
    if latest.peak_temp_c is None:
        return False, "最近批次尚未记录峰值温度，不能标记为已出灰"
    if latest.peak_temp_c < MIN_PEAK_TEMP_FOR_DRAWN:
        return (
            False,
            f"最近批次峰值温度 {latest.peak_temp_c}℃ 低于 {MIN_PEAK_TEMP_FOR_DRAWN:.0f}℃，不能标记为已出灰",
        )
    return True, ""


def assert_can_set_pond_status(pond: Pond, new_status: str) -> None:
    if new_status not in Pond.STATUS_CHOICES:
        raise RuleError(f"无效状态：{new_status}")
    if new_status == Pond.STATUS_DRAWN:
        ok, msg = can_mark_pond_drawn(pond)
        if not ok:
            raise RuleError(msg)
