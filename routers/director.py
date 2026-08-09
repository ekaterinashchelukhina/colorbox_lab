import secrets
from typing import Optional
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy import and_, case, func, not_
from sqlalchemy.orm import Session

from database import get_db
from models import Order, User, Branch, Shift, Client
from utils import (
    templates, require_director, require_director_page, parse_photo_list, paginate_query,
    scope_query_to_branch, parse_optional_id, apply_date_range_filter, CANCELLED_STATUS,
)

router = APIRouter(prefix="/director")


def _apply_shift_filters(query, user, branch_id, colorist_id, date_from, date_to):
    query = scope_query_to_branch(query, Shift, user, branch_id)
    if colorist_id is not None:
        query = query.filter(Shift.user_id == colorist_id)
    return apply_date_range_filter(query, Shift.start_time, date_from, date_to)


def _active_orders_query(db: Session, user: User, branch_id: Optional[str]):
    """Базовый запрос "активных" заказов филиала (или всех филиалов для директора):
    ещё не выданных или выданных, но не оплаченных; отменённые сюда не попадают —
    они уходят в архив. Возвращает (query, current_branch)."""
    query = db.query(Order).order_by(Order.created_at.desc())
    query = scope_query_to_branch(query, Order, user, branch_id)
    query = query.filter(
        Order.status != CANCELLED_STATUS,
        not_(and_(Order.status == "Выдано", Order.is_paid == True)),
    )

    b_id = parse_optional_id(branch_id)
    current_branch = db.query(Branch).filter(Branch.id == b_id).first() if b_id is not None else None
    return query, current_branch


def _director_dashboard_stats(db: Session, user: User, branch_id: Optional[str]):
    query, current_branch = _active_orders_query(db, user, branch_id)
    shifts_query = db.query(Shift).join(User).filter(Shift.end_time == None).order_by(Shift.start_time.desc())
    shifts_query = scope_query_to_branch(shifts_query, Shift, user, branch_id)

    b_id = parse_optional_id(branch_id)
    branch_filter = [Order.branch_id == b_id] if b_id is not None else []

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
def director_dashboard(request: Request, branch_id: Optional[str] = None, db: Session = Depends(get_db),
                       user: User = Depends(require_director_page)):
    branches = db.query(Branch).all()
    stats = _director_dashboard_stats(db, user, branch_id)

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
    stats = _director_dashboard_stats(db, user, branch_id)
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
    query, current_branch = _active_orders_query(db, user, branch_id)
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
    # Одноразовый токен нового сотрудника (см. add_user) — читаем и сразу гасим куку,
    # чтобы страницу нельзя было перезагрузить и увидеть токен повторно.
    new_token = request.cookies.get("flash_new_token")
    response = templates.TemplateResponse(request=request, name="director_users.html", context={
        "users": db.query(User).all(), "branches": db.query(Branch).all(), "current_username": user.username,
        "new_token": new_token,
    })
    if new_token:
        response.delete_cookie("flash_new_token", samesite="lax", secure=request.url.scheme == "https")
    return response


@router.get("/shifts/print")
def print_shifts_report(request: Request, branch_id: Optional[str] = None, colorist_id: Optional[str] = None,
                        date_from: Optional[str] = None, date_to: Optional[str] = None,
                        db: Session = Depends(get_db), user: User = Depends(require_director)):
    b_id = parse_optional_id(branch_id)
    c_id = parse_optional_id(colorist_id)

    # Отчёт только по колористам — смены менеджеров сюда не попадают
    shifts_query = db.query(Shift).join(User).filter(
        Shift.end_time != None, User.role == "Колорист"
    ).order_by(Shift.start_time.desc())
    shifts_query = _apply_shift_filters(shifts_query, user, b_id, c_id, date_from, date_to)
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
    if not branch:
        return RedirectResponse(url="/director/branches?success=branch_delete", status_code=303)

    # Иначе без cascade delete в БД останутся заказы/клиенты/сотрудники с "висячим" branch_id,
    # либо (для FK без ON DELETE) commit упадёт по IntegrityError — отказываем заранее и явно.
    has_dependents = (
        db.query(User).filter(User.branch_id == branch_id).first()
        or db.query(Client).filter(Client.branch_id == branch_id).first()
        or db.query(Order).filter(Order.branch_id == branch_id).first()
    )
    if has_dependents:
        return RedirectResponse(url="/director/branches?error=branch_in_use", status_code=303)

    db.delete(branch)
    db.commit()
    return RedirectResponse(url="/director/branches?success=branch_delete", status_code=303)


@router.post("/user/add")
def add_user(request: Request, username_new: str = Form(...), role: str = Form(...), branch_id: int = Form(...),
             db: Session = Depends(get_db), user: User = Depends(require_director)):
    # /login сравнивает по обрезанному имени (clean_username = username.strip()) — не обрежь
    # здесь, и случайный пробел в конце сделает учётку нерабочей с виду верным токеном.
    clean_username = username_new.strip()
    if db.query(User).filter(User.username == clean_username).first():
        return HTMLResponse("Ошибка: Пользователь с таким логином уже существует.")

    employee_token = secrets.token_hex(16)
    db.add(User(username=clean_username, password_hash=None, role=role, branch_id=branch_id, token=employee_token))
    db.commit()

    # Токен — секрет (это единственный "пароль" сотрудника), поэтому не кладём его
    # в query string: URL оседает в логах сервера/прокси и истории браузера. Вместо
    # этого — одноразовая httponly-кука, которую /director/users прочитает и сразу
    # удалит на следующем запросе.
    response = RedirectResponse(url=f"/director/users?success=user&new_name={clean_username}", status_code=303)
    response.set_cookie(key="flash_new_token", value=employee_token, max_age=60,
                        httponly=True, samesite="lax", secure=request.url.scheme == "https")
    return response


@router.post("/user/delete/{user_id}")
def delete_user(request: Request, user_id: int, db: Session = Depends(get_db),
                current_user: User = Depends(require_director)):
    target_user = db.query(User).filter(User.id == user_id).first()
    if target_user:
        if target_user.id == current_user.id:
            return HTMLResponse("Ошибка: Нельзя удалить собственную учетную запись.")

        # Отвязываем колориста/менеджера от старых заказов — иначе delete упадёт по FK
        # (manager_id/colorist_id не имеют ON DELETE, а сами заказы удалять нельзя)
        db.query(Order).filter(Order.colorist_id == user_id).update({"colorist_id": None})
        db.query(Order).filter(Order.manager_id == user_id).update({"manager_id": None})

        # Удаляем смены сотрудника
        db.query(Shift).filter(Shift.user_id == user_id).delete()

        # Безопасно удаляем пользователя
        db.delete(target_user)
        db.commit()
    return RedirectResponse(url="/director/users?success=user_delete", status_code=303)


@router.get("/shifts")
def director_shifts_list(request: Request, branch_id: Optional[str] = None, colorist_id: Optional[str] = None,
                         date_from: Optional[str] = None, date_to: Optional[str] = None, page: int = 1,
                         db: Session = Depends(get_db), user: User = Depends(require_director_page)):
    """Список всех смен для директора"""
    branches = db.query(Branch).all()
    # Отчёт только по колористам — смены менеджеров сюда не попадают
    query = db.query(Shift).join(User).filter(
        Shift.end_time != None, User.role == "Колорист"
    ).order_by(Shift.start_time.desc())

    b_id = parse_optional_id(branch_id)
    current_branch = db.query(Branch).filter(Branch.id == b_id).first() if b_id is not None else None
    c_id = parse_optional_id(colorist_id)

    query = _apply_shift_filters(query, user, b_id, c_id, date_from, date_to)
    shifts, page, total_pages, total = paginate_query(query, page)

    colorists = db.query(User).filter(User.role == "Колорист").order_by(User.username).all()

    return templates.TemplateResponse(
        request=request,
        name="director_shifts.html",
        context={
            "shifts": shifts,
            "branches": branches,
            "current_branch": current_branch,
            "colorists": colorists,
            "page": page, "total_pages": total_pages, "total": total,
            "filters": {
                "branch_id": branch_id or "", "colorist_id": colorist_id or "",
                "date_from": date_from or "", "date_to": date_to or ""
            }
        }
    )


@router.get("/shift/{shift_id}")
def director_shift_detail(request: Request, shift_id: int, db: Session = Depends(get_db),
                          user: User = Depends(require_director_page)):
    """Детальный просмотр фотографий конкретной смены"""
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