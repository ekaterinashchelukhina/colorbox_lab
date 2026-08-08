import json
from datetime import datetime
from typing import List

from fastapi import APIRouter, Request, Depends, UploadFile, File, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from database import get_db
from models import Order, Shift, User
from utils import get_current_user, templates, require_login, save_uploaded_photos

router = APIRouter()


@router.get("/colorist")
def colorist_dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)
    if not user.role or user.role.lower() != "колорист":
        return RedirectResponse(url="/dashboard", status_code=303)

    active_shift = db.query(Shift).filter(Shift.user_id == user.id, Shift.end_time == None).first()
    orders = []
    if active_shift:
        orders = db.query(Order).filter(
            Order.branch_id == user.branch_id,
            Order.status.in_(["В очереди", "В работе", "Переделка"])
        ).order_by(
            Order.is_express.desc(), Order.rework_count.desc(), Order.created_at.asc()
        ).all()

    return templates.TemplateResponse(request=request, name="colorist_dashboard.html", context={
        "username": user.username, "active_shift": active_shift, "orders": orders
    })


@router.get("/shift/end-screen")
def end_shift_screen(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.role or user.role.lower() != "колорист":
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="end_shift.html",
        context={"username": user.username}
    )


@router.post("/shift/start")
def start_shift(
    request: Request,
    client_time: str = Form(None),
    photos: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_login)
):
    # Используем время устройства или текущее серверное как резерв
    start_dt = datetime.fromisoformat(client_time) if client_time else datetime.now()

    saved_files = save_uploaded_photos(photos, user.id, "start")

    new_shift = Shift(
        user_id=user.id,
        branch_id=user.branch_id,
        start_time=start_dt,
        start_photos=json.dumps(saved_files)
    )
    db.add(new_shift)
    db.commit()
    return RedirectResponse(url="/colorist", status_code=303)


@router.post("/shift/end")
def end_shift(
    request: Request,
    client_time: str = Form(None),
    photos: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_login)
):
    active_shift = db.query(Shift).filter(Shift.user_id == user.id, Shift.end_time == None).first()
    if active_shift:
        end_dt = datetime.fromisoformat(client_time) if client_time else datetime.now()

        saved_files = save_uploaded_photos(photos, user.id, "end")

        active_shift.end_time = end_dt
        active_shift.end_photos = json.dumps(saved_files)
        db.commit()

    return RedirectResponse(url="/colorist", status_code=303)