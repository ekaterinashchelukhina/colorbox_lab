from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, Form, Depends, UploadFile, File
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from database import get_db
from models import Order, Client, User, Branch, Shift
from utils import (
    get_current_user, save_order_photo, templates, require_login,
    scope_query_to_branch, utc_now, paginate_query, user_has_role, display_role,
    apply_date_range_filter, parse_optional_id, get_in_branch_or_none, InvalidImageError,
    CANCELLED_STATUS, error_redirect,
)

router = APIRouter()

SERVICE_TYPES = ["Подбор", "Слив по коду", "Экспресс-подбор", "Готовая автоэмаль"]
# Эти два типа услуг требуют полного фотоконтроля (деталь до/после, фото рецепта) —
# остальным (Слив по коду, Готовая автоэмаль) достаточно фото весов.
PHOTO_REQUIRED_SERVICE_TYPES = ["Подбор", "Экспресс-подбор"]

# Единственные статусы, которые можно выставить через /order/{id}/status. "Отменен"
# сюда намеренно не входит — для него отдельный роут /order/{id}/cancel с проверкой
# роли "менеджер". Без этого списка new_status принял бы любую строку из формы.
ORDER_STATUSES = ["В очереди", "В работе", "Готово", "Ожидает выдачи", "Выдано"]

# "В работе" выставляется только нажатием "Взять в работу" на colorist_dashboard.html,
# "Готово" — только "Сдать заказ" на colorist_order.html. У менеджера в select на
# order_detail.html этих вариантов нет вообще, но без проверки здесь ничто не мешало
# отправить их прямым запросом в обход интерфейса.
COLORIST_ONLY_STATUSES = ["В работе", "Готово"]

# Заказ в одном из этих статусов — фактически архив: закрыт для любых правок (фото,
# финансы, комментарии, переназначение колориста, смена статуса колористом), кроме
# единственного сценария выхода — /order/{id}/rework, который сам требует "Выдано"
# и явно, осознанно открывает заказ заново.
LOCKED_STATUSES = ["Выдано", CANCELLED_STATUS]

# Соответствие photo_type из формы загрузки полю заказа, куда сохранить путь к файлу.
PHOTO_TYPE_FIELDS = {
    "detail": "photo_detail", "scales": "photo_scales", "after": "photo_after",
    "rework_scales": "rework_photo_scales", "rework_after": "rework_photo_after",
    "rework_test": "rework_photo_test", "recipe": "recipe_photo",
}


def _manager_shift_not_started(db: Session, user: User) -> bool:
    """True, если это менеджер и у него нет активной смены."""
    if not user_has_role(user, "менеджер"):
        return False
    active_shift = db.query(Shift).filter(Shift.user_id == user.id, Shift.end_time == None).first()
    return active_shift is None


@router.post("/manager/shift/start")
def manager_start_shift(request: Request,
                        db: Session = Depends(get_db), user: User = Depends(require_login)):
    """Упрощённый старт смены для менеджера: без фото и без отчёта."""
    if not user_has_role(user, "менеджер"):
        return RedirectResponse(url="/dashboard", status_code=303)

    active_shift = db.query(Shift).filter(Shift.user_id == user.id, Shift.end_time == None).first()
    if not active_shift:
        db.add(Shift(user_id=user.id, branch_id=user.branch_id, start_time=utc_now()))
        db.commit()

    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/manager/shift/end")
def manager_end_shift(request: Request,
                      db: Session = Depends(get_db), user: User = Depends(require_login)):
    """Упрощённое завершение смены для менеджера: без фото и без отчёта."""
    if not user_has_role(user, "менеджер"):
        return RedirectResponse(url="/dashboard", status_code=303)

    active_shift = db.query(Shift).filter(Shift.user_id == user.id, Shift.end_time == None).first()
    if active_shift:
        active_shift.end_time = utc_now()
        db.commit()

    return RedirectResponse(url="/dashboard", status_code=303)


def _require_manager_or_director(user: User) -> Optional[RedirectResponse]:
    """Архив и клиентская база — не рабочая зона колориста: в его интерфейсе нет ссылок
    ни туда, ни сюда, а архив к тому же показывает цену и статус оплаты заказа —
    в /order/{id}/finance это явно описано как зона менеджера/директора, не колориста."""
    if not (user_has_role(user, "менеджер") or user_has_role(user, "директор")):
        return RedirectResponse(url="/dashboard", status_code=303)
    return None


def _filtered_archive_query(db: Session, user: User, branch_id: Optional[str],
                            colorist_id: Optional[str], date_from: Optional[str], date_to: Optional[str],
                            service_type: Optional[str] = None):
    query = db.query(Order).filter(Order.status.in_(["Выдано", CANCELLED_STATUS]))
    query = scope_query_to_branch(query, Order, user, branch_id)

    colorist_id = parse_optional_id(colorist_id)
    if colorist_id is not None:
        query = query.filter(Order.colorist_id == colorist_id)

    if service_type:
        query = query.filter(Order.service_type == service_type)

    query = apply_date_range_filter(query, Order.created_at, date_from, date_to)

    return query.order_by(Order.created_at.desc())


@router.get("/archive")
def view_archive(request: Request, branch_id: Optional[str] = None, colorist_id: Optional[str] = None,
                 date_from: Optional[str] = None, date_to: Optional[str] = None,
                 service_type: Optional[str] = None, page: int = 1,
                 db: Session = Depends(get_db), user: User = Depends(require_login)):
    guard = _require_manager_or_director(user)
    if guard:
        return guard

    user_role = display_role(user)
    archive_query = _filtered_archive_query(db, user, branch_id, colorist_id, date_from, date_to,
                                            service_type)
    archived_orders, page, total_pages, total = paginate_query(archive_query, page)

    colorist_query = db.query(User).filter(User.role == "Колорист")
    colorist_query = scope_query_to_branch(colorist_query, User, user)

    return templates.TemplateResponse(request=request, name="archive.html", context={
        "orders": archived_orders, "role": user_role,
        "branches": db.query(Branch).all() if user_role == "Директор" else [],
        "colorists": colorist_query.order_by(User.username).all(),
        "service_types": SERVICE_TYPES,
        "page": page, "total_pages": total_pages, "total": total,
        "filters": {
            "branch_id": branch_id or "", "colorist_id": colorist_id or "",
            "date_from": date_from or "", "date_to": date_to or "", "service_type": service_type or ""
        }
    })


@router.get("/archive/print")
def print_archive(request: Request, branch_id: Optional[str] = None, colorist_id: Optional[str] = None,
                  date_from: Optional[str] = None, date_to: Optional[str] = None,
                  service_type: Optional[str] = None,
                  db: Session = Depends(get_db), user: User = Depends(require_login)):
    guard = _require_manager_or_director(user)
    if guard:
        return guard

    user_role = display_role(user)
    orders = _filtered_archive_query(db, user, branch_id, colorist_id, date_from, date_to,
                                     service_type).all()
    total_price = sum(o.price for o in orders if o.price and o.status != CANCELLED_STATUS)

    return templates.TemplateResponse(request=request, name="print_archive.html",
                                      context={"orders": orders, "role": user_role, "total_price": total_price})


@router.get("/new-order")
def show_new_order_form(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/")
    if not user_has_role(user, "менеджер"):
        return RedirectResponse(url="/dashboard", status_code=303)
    if _manager_shift_not_started(db, user):
        return RedirectResponse(url="/dashboard", status_code=303)
    clients = db.query(Client).filter(Client.branch_id == user.branch_id).order_by(Client.name).all()
    return templates.TemplateResponse(request=request, name="new_order.html", context={"clients": clients})


def _get_or_create_client(db: Session, name: str, branch_id: int) -> Client:
    """Находит клиента по имени в филиале или создаёт нового."""
    client = db.query(Client).filter(Client.name == name, Client.branch_id == branch_id).first()
    if not client:
        client = Client(name=name, branch_id=branch_id)
        db.add(client)
        db.commit()
        db.refresh(client)
    return client


@router.post("/new-order")
def create_order(
        request: Request, client_name: str = Form(...), car: str = Form(...), detail: str = Form(...),
        paint_code: Optional[str] = Form(None), service_type: str = Form(...), target_volume: float = Form(...),
        deadline: str = Form(...), manager_comment: str = Form(None),
        file: UploadFile = File(None),
        db: Session = Depends(get_db), manager: User = Depends(require_login)
):
    if not user_has_role(manager, "менеджер"):
        return RedirectResponse(url="/dashboard", status_code=303)
    if _manager_shift_not_started(db, manager):
        # На /dashboard, не /new-order — сама форма /new-order тоже требует активную
        # смену и без неё редиректит на /dashboard, роняя ?error= по дороге.
        return error_redirect("/dashboard", "Сначала начните смену!")
    if not manager.branch_id:
        return error_redirect("/new-order", "Нет привязки к филиалу!")
    if target_volume <= 0:
        return error_redirect("/new-order", "Требуемый объём должен быть больше нуля!")
    if service_type in PHOTO_REQUIRED_SERVICE_TYPES and (not file or not file.filename):
        return error_redirect("/new-order", "Отсутствует фото детали!")

    client = _get_or_create_client(db, client_name, manager.branch_id)

    # Naive UTC, как и все остальные DateTime-колонки (см. database.utc_now) — без этого
    # сравнение с utc_now() в будущем (например, отчёт по просроченным заказам) упадёт
    # с TypeError на смешивании naive/aware datetime.
    deadline_dt = datetime.strptime(deadline, "%Y-%m-%d").replace(hour=18, minute=0)
    is_express = True if service_type == "Экспресс-подбор" else False
    clean_paint_code = paint_code.strip() if paint_code else ""

    new_order = Order(
        branch_id=manager.branch_id, client_id=client.id, manager_id=manager.id,
        car=car, detail=detail, paint_code=clean_paint_code, category="Не указана",
        service_type=service_type, target_volume=target_volume, is_express=is_express,
        price=0.0, deadline_at=deadline_dt, manager_comment=manager_comment, created_at=utc_now()
    )
    db.add(new_order)
    db.commit()
    db.refresh(new_order)

    if file and file.filename:
        try:
            new_order.photo_detail = save_order_photo(file, f"order_{new_order.id}_detail.jpg")
        except InvalidImageError as e:
            # Заказ уже создан (commit выше) — ведём на его карточку, а не на пустую
            # форму, чтобы менеджер мог просто перезагрузить фото на месте.
            return error_redirect(f"/order/{new_order.id}", str(e))
        db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)


@router.get("/order/{order_id}")
def view_order(request: Request, order_id: int, db: Session = Depends(get_db),
               user: User = Depends(require_login)):
    order = get_in_branch_or_none(db, Order, order_id, user)
    if not order:
        return RedirectResponse(url="/dashboard", status_code=303)

    context = {"order": order, "viewer_id": user.id}
    if user_has_role(user, "колорист"):
        template_name = "colorist_order.html"
    elif user_has_role(user, "директор"):
        template_name = "director_order_detail.html"
    else:
        template_name = "order_detail.html"
        # Список колористов филиала — для формы "передать другому колористу"
        context["colorists"] = db.query(User).filter(
            User.role == "Колорист", User.branch_id == order.branch_id
        ).order_by(User.username).all()
    return templates.TemplateResponse(request=request, name=template_name, context=context)


def _missing_completion_photo(order: Order, new_status: str, is_rework_cycle: bool) -> Optional[str]:
    """Проверяет, хватает ли обязательных фото для перехода в new_status.
    Возвращает текст ошибки или None, если всё на месте."""
    needs_full_photo_set = order.service_type in PHOTO_REQUIRED_SERVICE_TYPES

    if new_status == "В работе" and not is_rework_cycle and needs_full_photo_set and not order.photo_detail:
        return "Нет фото детали до работы!"
    if new_status == "Готово":
        if is_rework_cycle:
            if not order.rework_photo_scales or not order.rework_photo_after or not order.rework_photo_test:
                return "Отсутствует фотоконтроль доколеровки!"
        # Весы обязательны всегда; фото "после" — только для Подбора/Экспресс-подбора.
        elif not order.photo_scales or (needs_full_photo_set and not order.photo_after):
            return "Отсутствует фотоконтроль!"
        if needs_full_photo_set and not order.recipe_photo:
            return "Отсутствует фото рецепта!"
    return None


@router.post("/order/{order_id}/status")
def update_order_status(request: Request, order_id: int, new_status: str = Form(...), actual_volume: float = Form(None),
                        db: Session = Depends(get_db), user: User = Depends(require_login)):
    # Смену статуса делают менеджер (форма на order_detail.html) и колорист (кнопка
    # "Сдать заказ" на colorist_order.html) — у директора своя страница заказа
    # полностью read-only, прав на смену статуса у него быть не должно.
    if not (user_has_role(user, "менеджер") or user_has_role(user, "колорист")):
        return RedirectResponse(url=f"/order/{order_id}", status_code=303)

    # Белый список статусов: без него new_status принял бы любую строку из формы
    # (включая "Отменен" в обход отдельного роута /order/{id}/cancel с проверкой
    # роли "менеджер").
    if new_status not in ORDER_STATUSES:
        return error_redirect(f"/order/{order_id}", "Недопустимый статус.")
    if new_status in COLORIST_ONLY_STATUSES and not user_has_role(user, "колорист"):
        return error_redirect(f"/order/{order_id}", "Этот статус выставляет только колорист.")
    # Менеджер вручную переводит заказ только в "Выдано" (на order_detail.html это
    # отдельная кнопка, не выпадающий список) — без этой проверки на сервере ничто
    # не мешало отправить прямым запросом и "В очереди" в обход доколеровки.
    if user_has_role(user, "менеджер") and new_status != "Выдано":
        return error_redirect(f"/order/{order_id}", "Менеджер может вручную перевести заказ только в статус «Выдано».")

    order = get_in_branch_or_none(db, Order, order_id, user)
    if order:
        if user_has_role(user, "менеджер"):
            # "Выдано" разрешено только из "Ожидает выдачи" — в этот статус заказ
            # переводит колорист через "Сдать заказ", уже пройдя все проверки
            # фотоконтроля в _missing_completion_photo(). Разреши "Выдано" из любого
            # статуса — и менеджер мог бы выдать заказ, который колорист вообще
            # не начинал делать.
            if order.status != "Ожидает выдачи":
                return error_redirect(f"/order/{order_id}", "Заказ ещё не готов к выдаче — фотоконтроль колориста не завершён.")
            if not order.price:
                return error_redirect(f"/order/{order_id}", "Сначала сохраните расчёт в блоке «Финансы и Оплата».")

        if user_has_role(user, "колорист"):
            # Без этой проверки тот же колорист, что вёл заказ, мог вернуть уже
            # выданный заказ обратно в "В работе" прямым POST — старые фото уже
            # на месте, значит _missing_completion_photo() ничего бы не поймал.
            # Единственный сценарий возврата выданного заказа в работу —
            # /order/{id}/rework (действие менеджера, с явным сбросом фото и
            # инкрементом счётчика доколеровок), не эта форма.
            if order.status in LOCKED_STATUSES:
                return error_redirect(f"/order/{order_id}", "Заказ уже выдан или отменён — статус изменить нельзя.")
            # Заказ уже закреплён за другим колористом (взят в работу или вернулся из
            # доколеровки — colorist_id при отправке на доколеровку не сбрасывается) —
            # чужой колорист не должен иметь возможность перехватить его себе через эту
            # форму. Переназначить может только менеджер через /reassign-colorist.
            if order.colorist_id is not None and order.colorist_id != user.id:
                return error_redirect(f"/order/{order_id}", "Этот заказ закреплён за другим колористом.")
            order.colorist_id = user.id

        # Заказ находится в активном цикле доколеровки, пока не сдан снова
        is_rework_cycle = order.rework_count > 0 and order.status != "Выдано"

        missing_photo = _missing_completion_photo(order, new_status, is_rework_cycle)
        if missing_photo:
            return error_redirect(f"/order/{order_id}", missing_photo)

        if new_status == "Готово":
            if actual_volume is not None and actual_volume <= 0:
                return error_redirect(f"/order/{order_id}", "Фактический объём должен быть больше нуля!")
            order.status = "Ожидает выдачи"
            if actual_volume is not None:
                order.actual_volume = actual_volume
        else:
            order.status = new_status
            if new_status == "Выдано":
                order.issued_at = utc_now()
        db.commit()

    return RedirectResponse(url="/colorist" if new_status == "Готово" else f"/order/{order_id}", status_code=303)


@router.post("/order/{order_id}/reassign-colorist")
def reassign_colorist(request: Request, order_id: int, colorist_id: int = Form(...),
                      db: Session = Depends(get_db), user: User = Depends(require_login)):
    """Менеджер только предлагает передать заказ другому колористу — colorist_id не
    меняется здесь. Реальный перенос происходит в transfer_respond(), и только когда
    согласны обе стороны (см. Order.pending_colorist_id/transfer_confirmed_by_*)."""
    if not user_has_role(user, "менеджер"):
        return RedirectResponse(url=f"/order/{order_id}", status_code=303)

    order = get_in_branch_or_none(db, Order, order_id, user)
    if not order:
        return RedirectResponse(url="/dashboard", status_code=303)
    if order.status in LOCKED_STATUSES:
        return error_redirect(f"/order/{order_id}", "Заказ уже выдан или отменён — колориста изменить нельзя.")
    if order.pending_colorist_id is not None:
        return error_redirect(f"/order/{order_id}", "Уже есть незавершённый запрос на передачу этого заказа.")

    # Новый колорист обязан быть колористом того же филиала, что и заказ — иначе
    # можно было бы передать заказ сотруднику, который его физически не увидит
    # в своей очереди (она отфильтрована по branch_id).
    new_colorist = db.query(User).filter(
        User.id == colorist_id, User.role == "Колорист", User.branch_id == order.branch_id
    ).first()
    if not new_colorist:
        return error_redirect(f"/order/{order_id}", "Такого колориста нет в этом филиале.")
    if order.colorist_id == new_colorist.id:
        return error_redirect(f"/order/{order_id}", "Заказ уже назначен этому колористу.")

    order.pending_colorist_id = new_colorist.id
    # Если заказ ещё вообще ни за кем не закреплён — отпускать некому, спрашиваем
    # согласия только у нового колориста.
    order.transfer_confirmed_by_current = order.colorist_id is None
    order.transfer_confirmed_by_new = False
    db.commit()
    return RedirectResponse(url=f"/order/{order_id}", status_code=303)


@router.post("/order/{order_id}/transfer-respond")
def transfer_respond(request: Request, order_id: int, action: str = Form(...),
                     db: Session = Depends(get_db), user: User = Depends(require_login)):
    """Согласие/отказ колориста на предложенную менеджером передачу заказа. И тот,
    у кого забирают заказ (order.colorist_id), и тот, кому предлагают
    (order.pending_colorist_id), должны отдельно принять — только тогда
    colorist_id реально меняется. Отказ любой стороны отменяет весь запрос."""
    if not user_has_role(user, "колорист"):
        return RedirectResponse(url=f"/order/{order_id}", status_code=303)
    if action not in ("accept", "decline"):
        return error_redirect(f"/order/{order_id}", "Недопустимое действие.")

    order = get_in_branch_or_none(db, Order, order_id, user)
    if not order or order.pending_colorist_id is None:
        return RedirectResponse(url=f"/order/{order_id}", status_code=303)

    is_current = order.colorist_id == user.id
    is_new = order.pending_colorist_id == user.id
    if not (is_current or is_new):
        return error_redirect(f"/order/{order_id}", "Этот запрос на передачу не касается вас.")

    # Заказ успели выдать/отменить, пока запрос висел (например, менеджер выдал его
    # прежнему колористу до ответа) — аннулируем запрос целиком, а не переносим заказ.
    if order.status in LOCKED_STATUSES:
        order.pending_colorist_id = None
        order.transfer_confirmed_by_current = False
        order.transfer_confirmed_by_new = False
        db.commit()
        return error_redirect(f"/order/{order_id}", "Заказ уже выдан или отменён — запрос на передачу отменён.")

    if action == "decline":
        order.pending_colorist_id = None
        order.transfer_confirmed_by_current = False
        order.transfer_confirmed_by_new = False
        db.commit()
        return RedirectResponse(url=f"/order/{order_id}", status_code=303)

    if is_current:
        order.transfer_confirmed_by_current = True
    if is_new:
        order.transfer_confirmed_by_new = True

    if order.transfer_confirmed_by_current and order.transfer_confirmed_by_new:
        order.colorist_id = order.pending_colorist_id
        order.pending_colorist_id = None
        order.transfer_confirmed_by_current = False
        order.transfer_confirmed_by_new = False

    db.commit()
    return RedirectResponse(url=f"/order/{order_id}", status_code=303)


@router.post("/order/{order_id}/transfer-cancel")
def transfer_cancel(request: Request, order_id: int, db: Session = Depends(get_db),
                    user: User = Depends(require_login)):
    """Менеджер отзывает свой же незавершённый запрос на передачу — не нужно ждать,
    пока обе стороны ответят, если запрос стал не нужен."""
    if not user_has_role(user, "менеджер"):
        return RedirectResponse(url=f"/order/{order_id}", status_code=303)

    order = get_in_branch_or_none(db, Order, order_id, user)
    if order and order.pending_colorist_id is not None:
        order.pending_colorist_id = None
        order.transfer_confirmed_by_current = False
        order.transfer_confirmed_by_new = False
        db.commit()
    return RedirectResponse(url=f"/order/{order_id}", status_code=303)


@router.post("/order/{order_id}/release")
def release_order(request: Request, order_id: int, db: Session = Depends(get_db),
                  user: User = Depends(require_login)):
    """Колорист отказывается от своего заказа — colorist_id сбрасывается, заказ
    возвращается в общую очередь филиала (виден любому колористу на смене, см.
    фильтр в colorist_dashboard()). Только владелец заказа может от него отказаться —
    иначе любой колорист мог бы снять чужой заказ с закрепления."""
    if not user_has_role(user, "колорист"):
        return RedirectResponse(url=f"/order/{order_id}", status_code=303)

    order = get_in_branch_or_none(db, Order, order_id, user)
    if order and order.colorist_id == user.id and order.status in ["В очереди", "В работе"]:
        order.colorist_id = None
        order.status = "В очереди"
        db.commit()
    return RedirectResponse(url="/colorist", status_code=303)


@router.post("/order/{order_id}/rework")
def send_order_to_rework(request: Request, order_id: int, db: Session = Depends(get_db),
                         user: User = Depends(require_login)):
    """Возвращает выданный заказ в очередь колориста на доколеровку. Право есть только
    у менеджера — как и у /order/{id}/cancel, ни у директора, ни у колориста."""
    if not user_has_role(user, "менеджер"):
        return RedirectResponse(url=f"/order/{order_id}", status_code=303)

    order = get_in_branch_or_none(db, Order, order_id, user)
    if order and order.status == "Выдано":
        order.status = "В очереди"
        order.rework_count += 1
        order.rework_photo_scales = None
        order.rework_photo_after = None
        order.rework_photo_test = None
        order.issued_at = None
        db.commit()
    return RedirectResponse(url=f"/order/{order_id}", status_code=303)


@router.post("/order/{order_id}/cancel")
def cancel_order(request: Request, order_id: int, db: Session = Depends(get_db),
                 user: User = Depends(require_login)):
    """"Удаление" заказа менеджером: не физическое удаление, а перевод в архив со статусом
    'Отменен'. Право есть только у менеджера — ни у директора, ни у колориста. Отменить
    можно только пока заказ ещё не взял в работу ни один колорист — colorist_id
    выставляется ровно в этот момент (см. update_order_status) и с тех пор не сбрасывается
    (кроме /release и /reassign-colorist), так что этой одной проверки достаточно и для
    "Готово"/"Ожидает выдачи"/"Выдано" — везде там колорист уже гарантированно назначен."""
    if not user_has_role(user, "менеджер"):
        return RedirectResponse(url=f"/order/{order_id}", status_code=303)

    order = get_in_branch_or_none(db, Order, order_id, user)
    if not order:
        return RedirectResponse(url="/dashboard", status_code=303)
    if order.status == "Выдано":
        return error_redirect(f"/order/{order_id}", "Нельзя отменить уже выданный заказ.")
    if order.colorist_id is not None:
        return error_redirect(f"/order/{order_id}", "Нельзя отменить заказ — колорист уже взял его в работу.")

    if order.status != CANCELLED_STATUS:
        order.status = CANCELLED_STATUS
        db.commit()
    return RedirectResponse(url="/archive", status_code=303)


@router.post("/order/{order_id}/upload")
def upload_photo(request: Request, order_id: int, photo_type: str = Form(...), file: UploadFile = File(...),
                 db: Session = Depends(get_db), user: User = Depends(require_login)):
    # Загрузка фото есть только на order_detail.html (менеджер) и colorist_order.html
    # (колорист) — у директора страница заказа read-only, он не должен иметь возможность
    # незаметно подменить фото-доказательства заказа в чужом филиале.
    if not (user_has_role(user, "менеджер") or user_has_role(user, "колорист")):
        return RedirectResponse(url=f"/order/{order_id}", status_code=303)

    # photo_type идёт прямо в ключ файла в хранилище — проверяем его по белому списку
    # ДО сохранения, иначе значение вроде "../../../static/css/legacy" даёт запись
    # произвольного файла (path traversal).
    field = PHOTO_TYPE_FIELDS.get(photo_type)
    if not field:
        return error_redirect(f"/order/{order_id}", "Недопустимый тип фото.")

    order = get_in_branch_or_none(db, Order, order_id, user)
    if not order:
        return RedirectResponse(url="/dashboard", status_code=303)
    # Выданный/отменённый заказ — архив: фото-доказательства менять нельзя даже
    # менеджеру (раньше можно было зайти на карточку из архива и подменить фото).
    if order.status in LOCKED_STATUSES:
        return error_redirect(f"/order/{order_id}", "Заказ уже выдан или отменён — фото изменить нельзя.")
    # Свой колорист может дозагрузить/поправить фото своего заказа; чужой — не должен
    # иметь возможность вмешаться в заказ, который ведёт не он (та же логика, что
    # в update_order_status).
    if user_has_role(user, "колорист") and order.colorist_id is not None and order.colorist_id != user.id:
        return error_redirect(f"/order/{order_id}", "Этот заказ закреплён за другим колористом.")

    if file and file.filename:
        try:
            photo_url = save_order_photo(file, f"order_{order_id}_{photo_type}.jpg")
        except InvalidImageError as e:
            return error_redirect(f"/order/{order_id}", str(e))
        setattr(order, field, photo_url)
        db.commit()
    return RedirectResponse(url=f"/order/{order_id}", status_code=303)


@router.post("/order/{order_id}/finance")
def update_order_finance(request: Request, order_id: int, price: str = Form("0"), is_paid: str = Form(None),
                         db: Session = Depends(get_db), user: User = Depends(require_login)):
    # Финансы заказа — зона ответственности менеджера/директора, не колориста
    if not (user_has_role(user, "менеджер") or user_has_role(user, "директор")):
        return RedirectResponse(url=f"/order/{order_id}", status_code=303)

    order = get_in_branch_or_none(db, Order, order_id, user)
    if order:
        if order.status in LOCKED_STATUSES:
            return error_redirect(f"/order/{order_id}", "Заказ уже выдан или отменён — расчёт изменить нельзя.")
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
                         db: Session = Depends(get_db), user: User = Depends(require_login)):
    order = get_in_branch_or_none(db, Order, order_id, user)
    if order:
        if order.status in LOCKED_STATUSES:
            return error_redirect(f"/order/{order_id}", "Заказ уже выдан или отменён — комментарий изменить нельзя.")
        # Каждая роль пишет только в свой комментарий, а не в чужой
        if comment_type == "manager" and (user_has_role(user, "менеджер") or user_has_role(user, "директор")):
            order.manager_comment = comment_text
        elif comment_type == "colorist" and user_has_role(user, "колорист"):
            # Чужой колорист не должен иметь возможность переписать заметку колориста,
            # который реально ведёт этот заказ — та же логика владения, что и везде.
            if order.colorist_id is not None and order.colorist_id != user.id:
                return error_redirect(f"/order/{order_id}", "Этот заказ закреплён за другим колористом.")
            order.colorist_comment = comment_text
        else:
            return error_redirect(f"/order/{order_id}", "Недостаточно прав для этого комментария.")
        db.commit()
    return RedirectResponse(url=f"/order/{order_id}", status_code=303)


@router.get("/order/{order_id}/print")
def print_order(request: Request, order_id: int, db: Session = Depends(get_db),
                user: User = Depends(require_login)):
    order = get_in_branch_or_none(db, Order, order_id, user)
    return templates.TemplateResponse(request=request, name="print_order.html",
                                      context={"order": order}) if order else RedirectResponse(url="/dashboard")


@router.get("/clients")
def view_clients(request: Request, q: Optional[str] = None, branch_id: Optional[str] = None, page: int = 1,
                 db: Session = Depends(get_db), user: User = Depends(require_login)):
    guard = _require_manager_or_director(user)
    if guard:
        return guard

    user_role = display_role(user)
    query = db.query(Client)
    query = scope_query_to_branch(query, Client, user, branch_id)

    if q:
        query = query.filter(Client.name.ilike(f"%{q}%"))

    query = query.order_by(Client.name)
    clients, page, total_pages, total = paginate_query(query, page)

    return templates.TemplateResponse(request=request, name="clients.html", context={
        "clients": clients, "role": user_role,
        "branches": db.query(Branch).all() if user_role == "Директор" else [],
        "page": page, "total_pages": total_pages, "total": total,
        "filters": {"q": q or "", "branch_id": branch_id or ""}
    })


@router.get("/new-client")
def show_new_client_form(request: Request, db: Session = Depends(get_db), user: User = Depends(require_login)):
    if not user_has_role(user, "менеджер"):
        return RedirectResponse(url="/clients", status_code=303)
    branch = db.query(Branch).filter(Branch.id == user.branch_id).first()
    return templates.TemplateResponse(request=request, name="new_client.html", context={"branch": branch})


@router.post("/new-client")
def create_client(request: Request, client_name: str = Form(...), branch_id: int = Form(...),
                  db: Session = Depends(get_db), manager: User = Depends(require_login)):
    if not user_has_role(manager, "менеджер"):
        return RedirectResponse(url="/clients", status_code=303)
    if not manager.branch_id:
        return error_redirect("/new-client", "Нет привязки к филиалу!")
    if branch_id != manager.branch_id:
        return error_redirect("/new-client", "Нельзя добавить клиента в чужой филиал!")

    clean_name = client_name.strip()
    if not clean_name:
        return error_redirect("/new-client", "Укажите имя клиента!")

    existing = db.query(Client).filter(Client.name == clean_name, Client.branch_id == manager.branch_id).first()
    if existing:
        return RedirectResponse(url="/clients", status_code=303)

    client = Client(name=clean_name, branch_id=manager.branch_id)
    db.add(client)
    db.commit()
    return RedirectResponse(url="/clients", status_code=303)


@router.get("/client/{client_id}")
def view_client(request: Request, client_id: int, date_from: Optional[str] = None, date_to: Optional[str] = None,
                service_type: Optional[str] = None,
                db: Session = Depends(get_db), user: User = Depends(require_login)):
    guard = _require_manager_or_director(user)
    if guard:
        return guard

    client = get_in_branch_or_none(db, Client, client_id, user)
    if not client:
        return RedirectResponse(url="/dashboard", status_code=303)

    query = db.query(Order).filter(Order.client_id == client_id)
    if service_type:
        query = query.filter(Order.service_type == service_type)
    query = apply_date_range_filter(query, Order.created_at, date_from, date_to)
    orders = query.order_by(Order.created_at.desc()).all()

    return templates.TemplateResponse(request=request, name="client_detail.html", context={
        "client": client, "orders": orders, "service_types": SERVICE_TYPES, "role": display_role(user),
        "filters": {"date_from": date_from or "", "date_to": date_to or "", "service_type": service_type or ""}
    })