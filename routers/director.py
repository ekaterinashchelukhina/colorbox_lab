import secrets
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy import and_, case, func, not_
from sqlalchemy.orm import Session

from database import get_db
from models import Order, User, Branch, Shift
from utils import get_current_user, templates, require_director, parse_photo_list

router = APIRouter(prefix="/director")


def _apply_shift_filters(query, branch_id, colorist_id, date_from, date_to):
    if branch_id:
        query = query.filter(Shift.branch_id == branch_id)
    if colorist_id:
        query = query.filter(Shift.user_id == colorist_id)
    if date_from:
        try:
            query = query.filter(Shift.start_time >= datetime.strptime(date_from, "%Y-%m-%d"))
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            query = query.filter(Shift.start_time <= dt_to)
        except ValueError:
            pass
    return query


def _director_dashboard_stats(db: Session, branch_id: Optional[str]):
    query = db.query(Order).order_by(Order.created_at.desc())
    shifts_query = db.query(Shift).join(User).filter(Shift.end_time == None).order_by(Shift.start_time.desc())

    branch_filter = []
    current_branch = None
    if branch_id and branch_id.isdigit():
        b_id = int(branch_id)
        branch_filter.append(Order.branch_id == b_id)
        query = query.filter(Order.branch_id == b_id)
        shifts_query = shifts_query.filter(Shift.branch_id == b_id)
        current_branch = db.query(Branch).filter(Branch.id == b_id).first()

    query = query.filter(not_(and_(Order.status == "Выдано", Order.is_paid == True)))
    orders = query.all()
    shifts = shifts_query.all()

    total_revenue = db.query(func.sum(Order.price)).filter(
        *branch_filter, Order.price.isnot(None), Order.price != 0,
        (Order.is_paid == True) | (Order.status == "Выдано")
    ).scalar() or 0.0

    volume_expr = func.coalesce(Order.actual_volume, Order.target_volume, 0.0)
    normalized_volume = case((volume_expr > 10, volume_expr / 1000.0), else_=volume_expr)
    total_paint_volume = db.query(func.sum(normalized_volume)).filter(*branch_filter).scalar() or 0.0

    # Накопительный счётчик: все доколеровки, включая уже сданные — не сбрасывается после выдачи
    total_reworks = db.query(func.sum(Order.rework_count)).filter(*branch_filter).scalar() or 0
    active_orders = len([o for o in orders if o.status not in ["Готово", "Выдано"]])

    return {
        "orders": orders, "shifts": shifts, "current_branch": current_branch,
        "total_revenue": total_revenue, "total_paint_volume": round(total_paint_volume, 1),
        "total_reworks": total_reworks, "active_orders": active_orders,
    }


@router.get("")
def director_dashboard(request: Request, branch_id: Optional[str] = None, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)
    if not user.role or user.role.lower() != "директор":
        return RedirectResponse(url="/dashboard", status_code=303)

    branches = db.query(Branch).all()
    stats = _director_dashboard_stats(db, branch_id)

    return templates.TemplateResponse(request=request, name="director_dashboard.html", context={
        "username": user.username, "orders": stats["orders"], "shifts": stats["shifts"],
        "branches": branches, "current_branch": stats["current_branch"],
        "total_revenue": stats["total_revenue"], "total_paint_volume": stats["total_paint_volume"],
        "total_reworks": stats["total_reworks"], "active_orders": stats["active_orders"],
    })


@router.get("/stats")
def director_dashboard_stats(branch_id: Optional[str] = None, db: Session = Depends(get_db),
                             user: User = Depends(require_director)):
    """Лёгкий JSON-снимок сводки для авто-обновления счётчиков на панели без перезагрузки страницы."""
    stats = _director_dashboard_stats(db, branch_id)
    return {
        "total_revenue": stats["total_revenue"],
        "total_paint_volume": stats["total_paint_volume"],
        "total_reworks": stats["total_reworks"],
        "active_orders": stats["active_orders"],
    }


@router.get("/orders")
def director_active_orders(request: Request, branch_id: Optional[str] = None, db: Session = Depends(get_db),
                           user: User = Depends(require_director)):
    branches = db.query(Branch).all()
    query = db.query(Order).order_by(Order.created_at.desc())
    current_branch = None
    if branch_id and branch_id.isdigit():
        b_id = int(branch_id)
        query = query.filter(Order.branch_id == b_id)
        current_branch = db.query(Branch).filter(Branch.id == b_id).first()

    query = query.filter(not_(and_(Order.status == "Выдано", Order.is_paid == True)))
    active_orders = query.all()

    return templates.TemplateResponse(request=request, name="director_orders.html", context={
        "orders": active_orders, "branches": branches, "current_branch": current_branch
    })


@router.get("/branches")
def manage_branches(request: Request, db: Session = Depends(get_db), user: User = Depends(require_director)):
    return templates.TemplateResponse(request=request, name="director_branches.html",
                                      context={"branches": db.query(Branch).all()})


@router.get("/users")
def manage_users(request: Request, db: Session = Depends(get_db), user: User = Depends(require_director)):
    return templates.TemplateResponse(request=request, name="director_users.html", context={
        "users": db.query(User).all(), "branches": db.query(Branch).all(), "current_username": user.username
    })


@router.get("/shifts/print")
def print_shifts_report(request: Request, branch_id: Optional[str] = None, colorist_id: Optional[str] = None,
                        date_from: Optional[str] = None, date_to: Optional[str] = None,
                        db: Session = Depends(get_db), user: User = Depends(require_director)):
    b_id = int(branch_id) if branch_id and branch_id.isdigit() else None
    c_id = int(colorist_id) if colorist_id and colorist_id.isdigit() else None

    # Отчёт только по колористам — смены менеджеров сюда не попадают
    shifts_query = db.query(Shift).join(User).filter(
        Shift.end_time != None, User.role == "Колорист"
    ).order_by(Shift.start_time.desc())
    shifts_query = _apply_shift_filters(shifts_query, b_id, c_id, date_from, date_to)
    shifts = shifts_query.all()
    for shift in shifts:
        shift.start_photos_list = parse_photo_list(shift.start_photos)
        shift.end_photos_list = parse_photo_list(shift.end_photos)

    return templates.TemplateResponse(request=request, name="shifts_report_print.html",
                                      context={"shifts": shifts})


@router.post("/branch/add")
def add_branch(request: Request, name: str = Form(...), db: Session = Depends(get_db),
               user: User = Depends(require_director)):
    db.add(Branch(name=name))
    db.commit()
    return RedirectResponse(url="/director/branches?success=branch", status_code=303)


@router.post("/branch/delete/{branch_id}")
def delete_branch(request: Request, branch_id: int, db: Session = Depends(get_db),
                  user: User = Depends(require_director)):
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if branch:
        db.delete(branch)
        db.commit()
    return RedirectResponse(url="/director/branches?success=branch_delete", status_code=303)


@router.post("/user/add")
def add_user(request: Request, username_new: str = Form(...), role: str = Form(...), branch_id: int = Form(...),
             db: Session = Depends(get_db), user: User = Depends(require_director)):
    if db.query(User).filter(User.username == username_new).first():
        return HTMLResponse("Ошибка: Пользователь с таким логином уже существует.")

    employee_token = secrets.token_hex(16)
    db.add(User(username=username_new, password_hash=None, role=role, branch_id=branch_id, token=employee_token))
    db.commit()
    return RedirectResponse(url=f"/director/users?success=user&new_token={employee_token}&new_name={username_new}",
                            status_code=303)


@router.post("/user/delete/{user_id}")
def delete_user(request: Request, user_id: int, db: Session = Depends(get_db),
                current_user: User = Depends(require_director)):
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
def director_shifts_list(request: Request, branch_id: Optional[str] = None, colorist_id: Optional[str] = None,
                         date_from: Optional[str] = None, date_to: Optional[str] = None,
                         db: Session = Depends(get_db)):
    """Список всех смен для директора"""
    user = get_current_user(request, db)
    if not user or (user.role and user.role.lower() != "директор"):
        return RedirectResponse(url="/dashboard", status_code=303)

    branches = db.query(Branch).all()
    # Отчёт только по колористам — смены менеджеров сюда не попадают
    query = db.query(Shift).join(User).filter(
        Shift.end_time != None, User.role == "Колорист"
    ).order_by(Shift.start_time.desc())

    current_branch = None
    b_id = int(branch_id) if branch_id and branch_id.isdigit() else None
    if b_id:
        current_branch = db.query(Branch).filter(Branch.id == b_id).first()
    c_id = int(colorist_id) if colorist_id and colorist_id.isdigit() else None

    query = _apply_shift_filters(query, b_id, c_id, date_from, date_to)
    shifts = query.all()

    colorists = db.query(User).filter(User.role == "Колорист").order_by(User.username).all()

    return templates.TemplateResponse(
        request=request,
        name="director_shifts.html",
        context={
            "shifts": shifts,
            "branches": branches,
            "current_branch": current_branch,
            "colorists": colorists,
            "filters": {
                "branch_id": branch_id or "", "colorist_id": colorist_id or "",
                "date_from": date_from or "", "date_to": date_to or ""
            }
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

    start_photos_list = parse_photo_list(shift.start_photos)
    end_photos_list = parse_photo_list(shift.end_photos)

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