import secrets
import json
import ast
from typing import Optional
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session

from database import get_db
from models import Order, User, Branch, Shift
from utils import get_current_user, templates

router = APIRouter(prefix="/director")


@router.get("")
def director_dashboard(request: Request, branch_id: Optional[str] = None, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)
    if not user.role or user.role.lower() != "директор":
        return RedirectResponse(url="/dashboard", status_code=303)

    branches = db.query(Branch).all()
    query = db.query(Order).order_by(Order.created_at.desc())
    shifts_query = db.query(Shift).join(User).filter(Shift.end_time == None).order_by(Shift.start_time.desc())

    current_branch = None
    if branch_id and branch_id.isdigit():
        b_id = int(branch_id)
        query = query.filter(Order.branch_id == b_id)
        shifts_query = shifts_query.filter(Shift.branch_id == b_id)
        current_branch = db.query(Branch).filter(Branch.id == b_id).first()

    all_orders = query.all()
    orders = [o for o in all_orders if not (o.status == "Выдано" and o.is_paid == True)]
    shifts = shifts_query.all()

    revenue_query = db.query(Order)
    if branch_id and branch_id.isdigit():
        revenue_query = revenue_query.filter(Order.branch_id == int(branch_id))

    all_network_orders = revenue_query.all()
    total_revenue = sum(o.price for o in all_network_orders if o.price and (o.is_paid or o.status == "Выдано"))

    total_paint_volume = 0.0
    for o in all_network_orders:
        vol = o.actual_volume if o.actual_volume is not None else (
            o.target_volume if o.target_volume is not None else 0.0)
        if vol > 10:
            vol = vol / 1000.0
        total_paint_volume += vol

    total_reworks = sum(o.rework_count for o in orders)
    active_orders = len([o for o in orders if o.status not in ["Готово", "Выдано"]])

    return templates.TemplateResponse(request=request, name="director_dashboard.html", context={
        "username": user.username, "orders": orders, "shifts": shifts,
        "branches": branches, "current_branch": current_branch,
        "total_revenue": total_revenue, "total_paint_volume": round(total_paint_volume, 1),
        "total_reworks": total_reworks, "active_orders": active_orders
    })


@router.get("/orders")
def director_active_orders(request: Request, branch_id: Optional[str] = None, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.role or user.role.lower() != "директор":
        return RedirectResponse(url="/", status_code=303)

    branches = db.query(Branch).all()
    query = db.query(Order).order_by(Order.created_at.desc())
    current_branch = None
    if branch_id and branch_id.isdigit():
        b_id = int(branch_id)
        query = query.filter(Order.branch_id == b_id)
        current_branch = db.query(Branch).filter(Branch.id == b_id).first()

    all_orders = query.all()
    active_orders = [o for o in all_orders if not (o.status == "Выдано" and o.is_paid == True)]

    return templates.TemplateResponse(request=request, name="director_orders.html", context={
        "orders": active_orders, "branches": branches, "current_branch": current_branch
    })


@router.get("/branches")
def manage_branches(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.role or user.role.lower() != "директор":
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request=request, name="director_branches.html",
                                      context={"branches": db.query(Branch).all()})


@router.get("/users")
def manage_users(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.role or user.role.lower() != "директор":
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request=request, name="director_users.html", context={
        "users": db.query(User).all(), "branches": db.query(Branch).all(), "current_username": user.username
    })


@router.get("/shifts/print")
def print_shifts_report(request: Request, branch_id: Optional[int] = None, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.role or user.role.lower() != "директор":
        return RedirectResponse(url="/", status_code=303)
    shifts_query = db.query(Shift).filter(Shift.end_time != None).order_by(Shift.start_time.desc())
    if branch_id:
        shifts_query = shifts_query.filter(Shift.branch_id == branch_id)
    return templates.TemplateResponse(request=request, name="shifts_report_print.html",
                                      context={"shifts": shifts_query.all()})


@router.post("/branch/add")
def add_branch(request: Request, name: str = Form(...), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.role or user.role.lower() != "директор":
        return RedirectResponse(url="/", status_code=303)
    db.add(Branch(name=name))
    db.commit()
    return RedirectResponse(url="/director/branches?success=branch", status_code=303)


@router.post("/branch/delete/{branch_id}")
def delete_branch(request: Request, branch_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.role or user.role.lower() != "директор":
        return RedirectResponse(url="/", status_code=303)
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if branch:
        db.delete(branch)
        db.commit()
    return RedirectResponse(url="/director/branches?success=branch_delete", status_code=303)


@router.post("/user/add")
def add_user(request: Request, username_new: str = Form(...), role: str = Form(...), branch_id: int = Form(...),
             db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.role or user.role.lower() != "директор":
        return RedirectResponse(url="/", status_code=303)
    if db.query(User).filter(User.username == username_new).first():
        return HTMLResponse("Ошибка: Пользователь с таким логином уже существует.")

    employee_token = secrets.token_hex(16)
    db.add(User(username=username_new, password_hash=None, role=role, branch_id=branch_id, token=employee_token))
    db.commit()
    return RedirectResponse(url=f"/director/users?success=user&new_token={employee_token}&new_name={username_new}",
                            status_code=303)


@router.post("/user/delete/{user_id}")
def delete_user(request: Request, user_id: int, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user or not current_user.role or current_user.role.lower() != "директор":
        return RedirectResponse(url="/", status_code=303)

    target_user = db.query(User).filter(User.id == user_id).first()
    if target_user:
        if target_user.id == current_user.id:
            return HTMLResponse("Ошибка: Нельзя удалить собственную учетную запись.")

        # Отвязываем колориста от старых заказов
        db.query(Order).filter(Order.colorist_id == user_id).update({"colorist_id": None})

        # Удаляем смены сотрудника
        db.query(Shift).filter(Shift.user_id == user_id).delete()

        # Безопасно удаляем пользователя
        db.delete(target_user)
        db.commit()
    return RedirectResponse(url="/director/users?success=user_delete", status_code=303)


@router.get("/shifts")
def director_shifts_list(request: Request, branch_id: Optional[str] = None, db: Session = Depends(get_db)):
    """Список всех смен для директора"""
    user = get_current_user(request, db)
    if not user or (user.role and user.role.lower() != "директор"):
        return RedirectResponse(url="/dashboard", status_code=303)

    branches = db.query(Branch).all()
    query = db.query(Shift).order_by(Shift.start_time.desc())

    current_branch = None
    if branch_id and branch_id.isdigit():
        b_id = int(branch_id)
        query = query.filter(Shift.branch_id == b_id)
        current_branch = db.query(Branch).filter(Branch.id == b_id).first()

    shifts = query.all()

    return templates.TemplateResponse(
        request=request,
        name="director_shifts.html",
        context={
            "shifts": shifts,
            "branches": branches,
            "current_branch": current_branch
        }
    )


@router.get("/shift/{shift_id}")
def director_shift_detail(request: Request, shift_id: int, db: Session = Depends(get_db)):
    """Детальный просмотр фотографий конкретной смены"""
    user = get_current_user(request, db)
    if not user or (user.role and user.role.lower() != "директор"):
        return RedirectResponse(url="/dashboard", status_code=303)

    shift = db.query(Shift).filter(Shift.id == shift_id).first()
    if not shift:
        return RedirectResponse(url="/director/shifts", status_code=303)

    # Умная функция для распаковки любых данных в список
    def parse_photos(photo_data):
        if not photo_data:
            return []
        if isinstance(photo_data, list):
            return photo_data
        if isinstance(photo_data, str):
            # Пробуем как JSON
            try:
                parsed = json.loads(photo_data)
                return parsed if isinstance(parsed, list) else [str(parsed)]
            except json.JSONDecodeError:
                pass
            # Пробуем как Python-строку (если база сохранила как "['file.jpg']")
            try:
                parsed = ast.literal_eval(photo_data)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass
            # Если это просто один путь текстом
            return [photo_data]
        return []

    start_photos_list = parse_photos(shift.start_photos)
    end_photos_list = parse_photos(shift.end_photos)

    return templates.TemplateResponse(
        request=request,
        name="director_shift_detail.html",
        context={
            "shift": shift,
            "start_photos_list": start_photos_list,
            "end_photos_list": end_photos_list
        }
    )


@router.get("/fix-orders")
def fix_orphaned_orders(db: Session = Depends(get_db)):
    """
    Временный роут для починки тестовой базы данных.
    Привязывает все "осиротевшие" заказы к филиалу Уфа (ID=2).
    """
    # Находим все заказы, у которых branch_id не равен 2 (включая None)
    orphaned_orders = db.query(Order).filter(
        (Order.branch_id != 2) | (Order.branch_id == None)
    ).all()

    for order in orphaned_orders:
        order.branch_id = 2

    db.commit()

    return HTMLResponse(
        "<h2>Все заказы успешно привязаны к филиалу Уфа!</h2>"
        "<a href='/director?branch_id=2'>Вернуться на панель директора</a>"
    )