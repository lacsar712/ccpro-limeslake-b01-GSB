from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import Plant, Pond
from app.services.rules import (
    RuleError,
    assert_can_set_pond_status,
    batch_is_peak_alert,
    latest_batch_for_pond,
    peak_target_gap,
    pond_peak_alert_batch,
)

bp = Blueprint("board", __name__, url_prefix="/board")

STATUS_LABELS = {
    Pond.STATUS_FILLING: "注水中",
    Pond.STATUS_SLAKING: "熟化中",
    Pond.STATUS_DRAWN: "已出灰",
}


def _slaking_alert_rows():
    """
    返回当前处于告警中的 (pond, batch) 列表（池为熟化中、最近班峰值已填
    且低于目标温超过 15℃）。告警状态不入库，全部由库内最新数据现算，
    保证专页、瓦片与库三者口径一致。
    """
    ponds = (
        Pond.query.options(selectinload(Pond.batches))
        .filter_by(status=Pond.STATUS_SLAKING)
        .join(Plant)
        .order_by(Plant.name, Pond.code)
        .all()
    )
    rows = []
    for pond in ponds:
        alert_batch = pond_peak_alert_batch(pond)
        if alert_batch is not None:
            rows.append((pond, alert_batch))
    return rows


@bp.app_context_processor
def inject_alert_count():
    return {"peak_alert_count": len(_slaking_alert_rows())}


@bp.route("/")
@login_required
def floor_plan():
    plants = Plant.query.order_by(Plant.name).all()
    plant_id_raw = request.args.get("plant_id", "").strip()
    active_plant = None
    if plant_id_raw.isdigit():
        active_plant = db.session.get(Plant, int(plant_id_raw))
    if active_plant is None and plants:
        active_plant = plants[0]

    ponds = []
    if active_plant:
        ponds = (
            Pond.query.options(selectinload(Pond.batches))
            .filter_by(plant_id=active_plant.id)
            .order_by(Pond.code)
            .all()
        )

    pond_cards = []
    for pond in ponds:
        batch = latest_batch_for_pond(pond)
        alert = batch_is_peak_alert(batch) and pond.status == Pond.STATUS_SLAKING
        pond_cards.append(
            {
                "pond": pond,
                "batch": batch,
                "alert": alert,
                "gap": peak_target_gap(batch) if alert else None,
            }
        )

    selected_id = request.args.get("pond", type=int)
    selected = None
    selected_batch = None
    selected_alert = False
    selected_gap = None
    if selected_id:
        selected_card = next(
            (c for c in pond_cards if c["pond"].id == selected_id), None
        )
        if selected_card:
            selected = selected_card["pond"]
            selected_batch = selected_card["batch"]
            selected_alert = selected_card["alert"]
            selected_gap = selected_card["gap"]

    return render_template(
        "board/floor.html",
        plants=plants,
        active_plant=active_plant,
        pond_cards=pond_cards,
        selected=selected,
        selected_batch=selected_batch,
        selected_alert=selected_alert,
        selected_gap=selected_gap,
        status_labels=STATUS_LABELS,
    )


@bp.route("/alerts")
@login_required
def peak_alerts():
    """峰值偏离告警专页：按厂列出告警中的熟化池。"""
    rows = _slaking_alert_rows()

    plant_groups = []
    for plant in Plant.query.order_by(Plant.name).all():
        items = [
            {
                "pond": pond,
                "batch": batch,
                "gap": peak_target_gap(batch),
            }
            for pond, batch in rows
            if pond.plant_id == plant.id
        ]
        if items:
            plant_groups.append({"plant": plant, "entries": items})

    return render_template(
        "board/alerts.html",
        plant_groups=plant_groups,
        total=len(rows),
        status_labels=STATUS_LABELS,
    )


@bp.route("/ponds/<int:pond_id>/ops", methods=["POST"])
@login_required
def pond_ops(pond_id: int):
    # 锁住池行：两人几乎同时改同一熟化班峰值时，同池请求在此串行，
    # 后一个请求基于已提交的新版本再覆盖，库里最终只落一版峰值，
    # 重定向后的瓦片与告警专页都读到同一入库值。
    pond = db.session.execute(
        db.select(Pond).where(Pond.id == pond_id).with_for_update()
    ).scalar_one_or_none()
    if pond is None:
        db.session.rollback()
        abort(404)

    status = request.form.get("status") or pond.status
    peak_raw = (request.form.get("peak_temp_c") or "").strip()
    notes = (request.form.get("batch_notes") or "").strip()

    batch = latest_batch_for_pond(pond)
    if batch is None:
        db.session.rollback()
        flash("该池尚无熟化批次，无法登记峰值或出灰", "error")
        return redirect(
            url_for("board.floor_plan", plant_id=pond.plant_id, pond=pond.id)
        )

    if peak_raw:
        try:
            batch.peak_temp_c = float(peak_raw)
        except ValueError:
            db.session.rollback()
            flash("峰值温度格式无效", "error")
            return redirect(
                url_for("board.floor_plan", plant_id=pond.plant_id, pond=pond.id)
            )

    batch.notes = notes

    try:
        assert_can_set_pond_status(pond, status)
        pond.status = status
        db.session.commit()
        flash(f"{pond.code} 已更新", "ok")
    except RuleError as exc:
        db.session.rollback()
        flash(str(exc), "error")

    return redirect(url_for("board.floor_plan", plant_id=pond.plant_id, pond=pond.id))
