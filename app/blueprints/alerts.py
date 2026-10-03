from flask import Blueprint, render_template
from flask_login import login_required

from app.models import Plant, Pond
from app.services.rules import (
    PEAK_TARGET_DEVIATION_ALERT_C,
    is_peak_deviation_alert,
    latest_batch_for_pond,
    peak_temp_deviation,
)

bp = Blueprint("alerts", __name__, url_prefix="/alerts")


@bp.route("/")
@login_required
def alert_list():
    """
    峰值偏离告警专页：按厂列出告警中的熟化池。
    名单与平面图瓦片共用 rules.is_peak_deviation_alert 同一口径，
    每次请求实时查库，保证页面、瓦片与库三方一致。
    """
    plants = Plant.query.order_by(Plant.name).all()
    sections = []
    total = 0
    for plant in plants:
        ponds = (
            Pond.query.filter_by(plant_id=plant.id, status=Pond.STATUS_SLAKING)
            .order_by(Pond.code)
            .all()
        )
        rows = []
        for pond in ponds:
            if not is_peak_deviation_alert(pond):
                continue
            rows.append(
                {
                    "pond": pond,
                    "batch": latest_batch_for_pond(pond),
                    "deviation": peak_temp_deviation(pond),
                }
            )
        if rows:
            sections.append({"plant": plant, "rows": rows})
            total += len(rows)

    return render_template(
        "alerts/list.html",
        sections=sections,
        total=total,
        threshold=PEAK_TARGET_DEVIATION_ALERT_C,
    )
