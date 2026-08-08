import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, Form, Depends, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session

from database import get_db
from models import Order, Client, RecipeItem
from utils import get_current_user, compress_and_save_image, templates, UPLOAD_DIR

router = APIRouter()


@router.get("/archive")
def view_archive(request: Request, branch_id: Optional[str] = None, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    user_role = user.role.capitalize() if user.role else ""
    query = db.query(Order).filter(Order.status == "Выдано")

    if user_role == "Директор":
        if branch_id and branch_id.isdigit():
            query = query.filter(Order.branch_id == int(branch_id))
    else:
        query = query.filter(Order.branch_id == user.branch_id)

    archived_orders = query.order_by(Order.created_at.desc()).all()
    return templates.TemplateResponse(request=request, name="archive.html",
                                      context={"orders": archived_orders, "role": user_role})


@router.get("/new-order")
def show_new_order_form(request: Request, db: Session = Depends(get_db)):
    if not get_current_user(request, db):
        return RedirectResponse(url="/")
    return templates.TemplateResponse(request=request, name="new_order.html")


@router.post("/new-order")
def create_order(
        request: Request, client_name: str = Form(...), car: str = Form(...), detail: str = Form(...),
        paint_code: str = Form(...), service_type: str = Form(...), target_volume: float = Form(...),
        deadline: str = Form(...), manager_comment: str = Form(None), file: UploadFile = File(None),
        db: Session = Depends(get_db)
):
    manager = get_current_user(request, db)
    if not manager:
        return RedirectResponse(url="/", status_code=303)
    if not manager.branch_id:
        return HTMLResponse("<h2>Ошибка: Нет привязки к филиалу!</h2>")
    if service_type in ["Подбор", "Экспресс-подбор"] and (not file or not file.filename):
        return HTMLResponse("<h2>Ошибка: Отсутствует фото детали!</h2>")

    client = db.query(Client).filter(Client.name == client_name, Client.branch_id == manager.branch_id).first()
    if not client:
        client = Client(name=client_name, branch_id=manager.branch_id)
        db.add(client)
        db.commit()
        db.refresh(client)

    deadline_dt = datetime.strptime(deadline, "%Y-%m-%d").replace(hour=18, minute=0, tzinfo=timezone.utc)
    is_express = True if service_type == "Экспресс-подбор" else False

    new_order = Order(
        branch_id=manager.branch_id, client_id=client.id, manager_id=manager.id,
        car=car, detail=detail, paint_code=paint_code, category="Не указана",
        service_type=service_type, target_volume=target_volume, is_express=is_express,
        price=0.0, deadline_at=deadline_dt, manager_comment=manager_comment
    )
    db.add(new_order)
    db.commit()
    db.refresh(new_order)

    if file and file.filename:
        file_path = f"{UPLOAD_DIR}/order_{new_order.id}_detail.jpg"
        compress_and_save_image(file, file_path)
        new_order.photo_detail = f"/{file_path}"
        db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)


@router.get("/order/{order_id}")
def view_order(request: Request, order_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        return RedirectResponse(url="/dashboard", status_code=303)

    user_role = user.role.lower() if user.role else ""
    template_name = "colorist_order.html" if user_role == "колорист" else "director_order_detail.html" if user_role == "директор" else "order_detail.html"
    return templates.TemplateResponse(request=request, name=template_name, context={"order": order})


@router.post("/order/{order_id}/status")
def update_order_status(request: Request, order_id: int, new_status: str = Form(...), actual_volume: float = Form(None),
                        db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)
    order = db.query(Order).filter(Order.id == order_id).first()
    if order:
        if user.role and user.role.lower() == "колорист":
            order.colorist_id = user.id

        # Проверки фотоконтроля
        if new_status == "В работе" and order.service_type in ["Подбор", "Экспресс-подбор"] and not order.photo_detail:
            return HTMLResponse("<h2>Ошибка: Нет фото детали до работы!</h2>")
        if new_status == "Готово":
            if order.service_type in ["Подбор", "Экспресс-подбор"] and (
                    not order.photo_scales or not order.photo_after):
                return HTMLResponse("<h2>Ошибка: Отсутствует фотоконтроль!</h2>")
            elif order.service_type not in ["Подбор", "Экспресс-подбор"] and not order.photo_scales:
                return HTMLResponse("<h2>Ошибка: Отсутствует фотоконтроль!</h2>")

        if new_status == "Переделка":
            order.status = "В очереди"
            order.rework_count += 1
        elif new_status == "Готово":
            order.status = "Ожидает выдачи"
            if actual_volume is not None:
                order.actual_volume = actual_volume
        else:
            order.status = new_status
        db.commit()

    return RedirectResponse(url="/colorist" if new_status == "Готово" else f"/order/{order_id}", status_code=303)


@router.post("/order/{order_id}/upload")
def upload_photo(request: Request, order_id: int, photo_type: str = Form(...), file: UploadFile = File(...),
                 db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)
    order = db.query(Order).filter(Order.id == order_id).first()
    if order and file and file.filename:
        file_path = f"{UPLOAD_DIR}/order_{order_id}_{photo_type}.jpg"
        compress_and_save_image(file, file_path)
        if photo_type == "detail":
            order.photo_detail = f"/{file_path}"
        elif photo_type == "scales":
            order.photo_scales = f"/{file_path}"
        elif photo_type == "after":
            order.photo_after = f"/{file_path}"
        db.commit()
    return RedirectResponse(url=f"/order/{order_id}", status_code=303)


@router.post("/order/{order_id}/recipe")
def add_recipe_item(request: Request, order_id: int, category: str = Form(...), toner_name: str = Form(...),
                    weight: float = Form(...), db: Session = Depends(get_db)):
    if get_current_user(request, db) and db.query(Order).filter(Order.id == order_id).first():
        db.add(RecipeItem(order_id=order_id, category=category, toner_name=toner_name, weight=weight))
        db.commit()
    return RedirectResponse(url=f"/order/{order_id}", status_code=303)


@router.post("/order/{order_id}/recipe/{item_id}/delete")
def delete_recipe_item(request: Request, order_id: int, item_id: int, db: Session = Depends(get_db)):
    if get_current_user(request, db):
        item = db.query(RecipeItem).filter(RecipeItem.id == item_id, RecipeItem.order_id == order_id).first()
        if item:
            db.delete(item)
            db.commit()
    return RedirectResponse(url=f"/order/{order_id}", status_code=303)


@router.post("/order/{order_id}/finance")
def update_order_finance(request: Request, order_id: int, price: str = Form("0"), is_paid: str = Form(None),
                         db: Session = Depends(get_db)):
    if get_current_user(request, db):
        order = db.query(Order).filter(Order.id == order_id).first()
        if order:
            try:
                clean_price = float(price.replace(",", "."))
            except ValueError:
                clean_price = 0.0
            order.price = clean_price
            order.is_paid = (is_paid == "on")
            db.commit()
    return RedirectResponse(url=f"/order/{order_id}", status_code=303)


@router.post("/order/{order_id}/comment")
def update_order_comment(request: Request, order_id: int, comment_type: str = Form(...), comment_text: str = Form(...),
                         db: Session = Depends(get_db)):
    if get_current_user(request, db):
        order = db.query(Order).filter(Order.id == order_id).first()
        if order:
            if comment_type == "manager":
                order.manager_comment = comment_text
            elif comment_type == "colorist":
                order.colorist_comment = comment_text
            db.commit()
    return RedirectResponse(url=f"/order/{order_id}", status_code=303)


@router.get("/order/{order_id}/print")
def print_order(request: Request, order_id: int, db: Session = Depends(get_db)):
    if not get_current_user(request, db):
        return RedirectResponse(url="/", status_code=303)
    order = db.query(Order).filter(Order.id == order_id).first()
    return templates.TemplateResponse(request=request, name="print_order.html",
                                      context={"order": order}) if order else RedirectResponse(url="/dashboard")


@router.get("/client/{client_id}")
def view_client(request: Request, client_id: int, db: Session = Depends(get_db)):
    if not get_current_user(request, db):
        return RedirectResponse(url="/", status_code=303)
    client = db.query(Client).filter(Client.id == client_id).first()
    return templates.TemplateResponse(request=request, name="client_detail.html",
                                      context={"client": client}) if client else RedirectResponse(url="/dashboard")