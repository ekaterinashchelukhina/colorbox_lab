import os
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Request, Depends, UploadFile, File
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from database import get_db
from models import Order, Shift
from utils import get_current_user, compress_and_save_image, templates, UPLOAD_DIR

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

@router.post("/shift/start")
def start_shift(request: Request, photos: List[UploadFile] = File(...), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    saved_files = []
    for photo in photos:
        if photo.filename:
            filename = f"{user.id}_start_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.jpg"
            file_path = os.path.join(UPLOAD_DIR, filename)
            compress_and_save_image(photo, file_path)
            saved_files.append(f"/{file_path}")

    new_shift = Shift(user_id=user.id, branch_id=user.branch_id, start_photos=",".join(saved_files))
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
                filename = f"{user.id}_end_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.jpg"
                file_path = os.path.join(UPLOAD_DIR, filename)
                compress_and_save_image(photo, file_path)
                saved_files.append(f"/{file_path}")

        active_shift.end_time = datetime.now(timezone.utc)
        active_shift.end_photos = ",".join(saved_files)
        db.commit()

    return RedirectResponse(url="/colorist", status_code=303)