import os
import json
from datetime import datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, Request, Depends, UploadFile, File
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from database import get_db
from models import Order, Shift
from utils import get_current_user, compress_and_save_image, templates, UPLOAD_DIR

router = APIRouter()

# Фиксированный часовой пояс для Уфы (UTC+5)
UFA_TZ = timezone(timedelta(hours=5))

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
def start_shift(request: Request, photos: List[UploadFile] = File(...), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    saved_files = []
    for photo in photos:
        if photo.filename:
            filename = f"{user.id}_start_{datetime.now(UFA_TZ).strftime('%Y%m%d%H%M%S%f')}.jpg"
            file_path = os.path.join(UPLOAD_DIR, filename)
            compress_and_save_image(photo, file_path)
            saved_files.append(file_path.replace("\\", "/"))

    # Сохраняем точное локальное время Уфы
    new_shift = Shift(
        user_id=user.id,
        branch_id=user.branch_id,
        start_time=datetime.now(UFA_TZ),
        start_photos=json.dumps(saved_files)
    )
    db.add(new_shift)
    db.commit()
    return RedirectResponse(url="/colorist", status_code=303)

@router.post("/shift/end")
def end_shift(request: Request, photos: List[UploadFile] = File(...), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    active_shift = db.query(Shift).filter(Shift.user_id == user.id, Shift.end_time == None).first()
    if active_shift:
        saved_files = []
        for photo in photos:
            if photo.filename:
                filename = f"{user.id}_end_{datetime.now(UFA_TZ).strftime('%Y%m%d%H%M%S%f')}.jpg"
                file_path = os.path.join(UPLOAD_DIR, filename)
                compress_and_save_image(photo, file_path)
                saved_files.append(file_path.replace("\\", "/"))

        # Сохраняем точное локальное время Уфы для закрытия
        active_shift.end_time = datetime.now(UFA_TZ)
        active_shift.end_photos = json.dumps(saved_files)
        db.commit()

    return RedirectResponse(url="/colorist", status_code=303)