"""石灰熟化池业务规则。"""

from __future__ import annotations

from app.models import Pond, SlakeBatch

MIN_PEAK_TEMP_FOR_DRAWN = 60.0

# 峰值偏离告警口径：熟化中池最近批次峰值已填，
# 且低于该班目标温超过 15℃ 即告警（仅提示，不挡出灰）。
PEAK_TARGET_DEVIATION_ALERT_C = 15.0


class RuleError(ValueError):
    """业务规则校验失败。"""


def latest_batch_for_pond(pond: Pond) -> SlakeBatch | None:
    if not pond.batches:
        return None
    return max(pond.batches, key=lambda b: b.started_at)


def peak_temp_deviation(pond: Pond) -> float | None:
    """
    最近批次峰值相对该班目标温的偏低值（℃）。
    无批次或峰值未记录时返回 None。
    """
    latest = latest_batch_for_pond(pond)
    if latest is None or latest.peak_temp_c is None:
        return None
    return latest.target_temp_c - latest.peak_temp_c


def is_peak_deviation_alert(pond: Pond) -> bool:
    """
    峰值偏离告警判定（平面图瓦片与告警专页共用同一口径，保证两边与库一致）：
    池处于「熟化中」，最近批次峰值已记录，且低于该班目标温超过 15℃。
    仅作提示，不参与出灰规则。
    """
    if pond.status != Pond.STATUS_SLAKING:
        return False
    deviation = peak_temp_deviation(pond)
    return deviation is not None and deviation > PEAK_TARGET_DEVIATION_ALERT_C


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
