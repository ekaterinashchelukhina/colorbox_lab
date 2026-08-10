import json
from typing import List

from fastapi import APIRouter, Request, Depends, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import get_db
from models import Order, Shift, User
from utils import (
    get_current_user, templates, require_login, save_uploaded_photos, utc_now, user_has_role,
    InvalidImageError,
)

router = APIRouter()


@router.get("/colorist")
def colorist_dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)
    if not user_has_role(user, "колорист"):
        return RedirectResponse(url="/dashboard", status_code=303)

    active_shift = db.query(Shift).filter(Shift.user_id == user.id, Shift.end_time == None).first()
    orders = []
    if active_shift:
        orders = db.query(Order).filter(
            Order.branch_id == user.branch_id,
            Order.status.in_(["В очереди", "В работе"]),
            # Свежий заказ (colorist_id ещё не назначен) виден всем колористам филиала —
            # это обычная общая очередь. А вот заказ, вернувшийся из доколеровки, уже
            # знает своего колориста (colorist_id остаётся с прошлого цикла работы,
            # send_order_to_rework его не сбрасывает) — такой заказ должен попадать
            # в очередь именно этого колориста, а не любого, кто первым откроет /colorist.
            or_(
                Order.status != "В очереди",
                Order.colorist_id.is_(None),
                Order.colorist_id == user.id,
            ),
        ).order_by(
            Order.is_express.desc(), Order.rework_count.desc(), Order.created_at.asc()
        ).all()

    return templates.TemplateResponse(request=request, name="colorist_dashboard.html", context={
        "username": user.username, "active_shift": active_shift, "orders": orders
    })


@router.get("/shift/end-screen")
def end_shift_screen(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user_has_role(user, "колорист"):
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="end_shift.html",
        context={"username": user.username}
    )


@router.post("/shift/start")
def start_shift(
    request: Request,
    photos: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_login)
):
    try:
        saved_files = save_uploaded_photos(photos, user.id, "start")
    except InvalidImageError as e:
        return HTMLResponse(f"<h2>Ошибка: {e}</h2>")

    new_shift = Shift(
        user_id=user.id,
        branch_id=user.branch_id,
        start_time=utc_now(),
        start_photos=json.dumps(saved_files)
    )
    db.add(new_shift)
    db.commit()
    return RedirectResponse(url="/colorist", status_code=303)


@router.post("/shift/end")
def end_shift(
    request: Request,
    photos: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_login)
):
    active_shift = db.query(Shift).filter(Shift.user_id == user.id, Shift.end_time == None).first()
    if active_shift:
        try:
            saved_files = save_uploaded_photos(photos, user.id, "end")
        except InvalidImageError as e:
            return HTMLResponse(f"<h2>Ошибка: {e}</h2>")

        active_shift.end_time = utc_now()
        active_shift.end_photos = json.dumps(saved_files)
        db.commit()

    return RedirectResponse(url="/colorist", status_code=303)