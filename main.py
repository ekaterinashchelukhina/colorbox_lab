import os
import secrets
from datetime import datetime, timezone
from typing import List, Optional
from PIL import Image

from fastapi import FastAPI, Request, Form, Depends, UploadFile, File, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from database import get_db
from models import Base, Order, User, Client, Branch, RecipeItem, Shift

app = FastAPI(title="Colorist CRM")

# Создаем папку для загрузок, если её нет
UPLOAD_DIR = "static/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")


def compress_and_save_image(file: UploadFile, path: str):
    """Функция для сжатия и оптимизации изображений перед сохранением."""
    img = Image.open(file.file)

    # Конвертируем в RGB, если это PNG с прозрачностью или палитра
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    # Ограничиваем максимальную ширину (1280px), сохраняя пропорции
    max_width = 1280
    if img.width > max_width:
        ratio = max_width / float(img.width)
        new_height = int(float(img.height) * float(ratio))
        img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)

    # Сохраняем в формате JPEG с качеством 85% и оптимизацией
    img.save(path, "JPEG", quality=85, optimize=True)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """Зависимость для авторизации пользователя по токену из кук."""
    token = request.cookies.get("access_token")
    if not token:
        return None
    return db.query(User).filter(User.token == token).first()


@app.get("/")
def read_root(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")


@app.post("/login")
def login(
        request: Request,
        username: str = Form(...),
        token: str = Form(...),
        db: Session = Depends(get_db)
):
    clean_username = username.strip()
    clean_token = token.strip()

    print(f"--- ПОПЫТКА ВХОДА --- Логин: [{clean_username}], Токен: [{clean_token}]")

    user = db.query(User).filter(
        User.username == clean_username,
        User.token == clean_token
    ).first()

    if not user:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error_message": "Неверный логин или токен доступа"}
        )

    user_role = user.role.lower() if user.role else ""
    if user_role == "директор":
        redirect_url = "/director"
    elif user_role == "колорист":
        redirect_url = "/colorist"
    else:
        redirect_url = "/dashboard"

    response = RedirectResponse(url=redirect_url, status_code=303)
    response.set_cookie(key="access_token", value=clean_token, httponly=True)

    return response


@app.get("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("access_token")
    return response


@app.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    if user.role and user.role.lower() == "колорист":
        return RedirectResponse(url="/colorist", status_code=303)

    if user.role and user.role.lower() == "директор":
        return RedirectResponse(url="/director", status_code=303)

    all_orders = db.query(Order).filter(Order.branch_id == user.branch_id).order_by(Order.created_at.desc()).all()
    orders = [o for o in all_orders if o.status != "Выдано"]

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "username": user.username,
            "orders": orders
        }
    )


# ==========================================
# БЛОК КОЛОРИСТА И СМЕН
# ==========================================

@app.get("/colorist")
def colorist_dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    if not user.role or user.role.lower() != "колорист":
        return RedirectResponse(url="/dashboard", status_code=303)

    active_shift = db.query(Shift).filter(
        Shift.user_id == user.id,
        Shift.end_time == None
    ).first()

    orders = []
    if active_shift:
        orders = db.query(Order).filter(
            Order.branch_id == user.branch_id,
            Order.status.in_(["В очереди", "В работе", "Переделка"])
        ).order_by(
            Order.is_express.desc(),
            Order.rework_count.desc(),
            Order.created_at.asc()
        ).all()

    return templates.TemplateResponse(
        request=request,
        name="colorist_dashboard.html",
        context={
            "username": user.username,
            "active_shift": active_shift,
            "orders": orders
        }
    )


@app.post("/shift/start")
def start_shift(
        request: Request,
        photos: List[UploadFile] = File(...),
        db: Session = Depends(get_db)
):
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

    new_shift = Shift(
        user_id=user.id,
        branch_id=user.branch_id,
        start_photos=",".join(saved_files)
    )
    db.add(new_shift)
    db.commit()

    return RedirectResponse(url="/colorist", status_code=303)


@app.post("/shift/end")
def end_shift(
        request: Request,
        photos: List[UploadFile] = File(...),
        db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    active_shift = db.query(Shift).filter(
        Shift.user_id == user.id,
        Shift.end_time == None
    ).first()

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


# ==========================================
# БЛОК АРХИВА
# ==========================================

@app.get("/archive")
def view_archive(
        request: Request,
        branch_id: Optional[str] = None,
        db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    user_role = user.role.capitalize() if user.role else ""
    user_branch_id = user.branch_id

    filter_branch = int(branch_id) if branch_id and branch_id.isdigit() else None

    query = db.query(Order).filter(Order.status == "Выдано")

    if user_role == "Директор":
        if filter_branch:
            query = query.filter(Order.branch_id == filter_branch)
    else:
        query = query.filter(Order.branch_id == user_branch_id)

    archived_orders = query.order_by(Order.created_at.desc()).all()

    return templates.TemplateResponse(
        request=request,
        name="archive.html",
        context={
            "orders": archived_orders,
            "role": user_role
        }
    )

@app.get("/new-order")
def show_new_order_form(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/")
    return templates.TemplateResponse(request=request, name="new_order.html")


@app.post("/new-order")
def create_order(
        request: Request,
        client_name: str = Form(...),
        car: str = Form(...),
        detail: str = Form(...),
        paint_code: str = Form(...),
        service_type: str = Form(...),
        target_volume: float = Form(...),
        deadline: str = Form(...),
        manager_comment: str = Form(None),
        file: UploadFile = File(None),
        db: Session = Depends(get_db)
):
    manager = get_current_user(request, db)
    if not manager:
        return RedirectResponse(url="/", status_code=303)

    if not manager.branch_id:
        return HTMLResponse("""
        <div style="font-family: Arial, sans-serif; padding: 40px; text-align: center;">
            <h2 style="color: #e74c3c;">Ошибка: Нет привязки к филиалу!</h2>
            <p style="font-size: 16px; color: #2c3e50; max-width: 500px; margin: 0 auto;">
                Ваша учетная запись (возможно, вы зашли под Директором) не привязана к конкретной лаборатории. Создавать заказы могут только менеджеры филиалов.
            </p>
            <br><br>
            <button onclick="window.history.back()" style="background: #3498db; color: white; padding: 10px 20px; border: none; border-radius: 5px; font-weight: bold; cursor: pointer;">← Вернуться назад</button>
        </div>
        """)

    if service_type in ["Подбор", "Экспресс-подбор"]:
        if not file or not file.filename:
            return HTMLResponse("""
            <div style="font-family: Arial, sans-serif; padding: 40px; text-align: center;">
                <h2 style="color: #e74c3c;">Ошибка: Отсутствует фото детали!</h2>
                <p style="font-size: 16px; color: #2c3e50; max-width: 500px; margin: 0 auto;">
                    Для услуг «Подбор» и «Экспресс-подбор» менеджер обязан загрузить фото образца при оформлении заказа.
                </p>
                <br><br>
                <button onclick="window.history.back()" style="background: #3498db; color: white; padding: 10px 20px; border: none; border-radius: 5px; font-weight: bold; cursor: pointer;">← Вернуться и добавить фото</button>
            </div>
            """)

    client = db.query(Client).filter(Client.name == client_name, Client.branch_id == manager.branch_id).first()

    if not client:
        client = Client(name=client_name, branch_id=manager.branch_id)
        db.add(client)
        db.commit()
        db.refresh(client)

    deadline_dt = datetime.strptime(deadline, "%Y-%m-%d").replace(hour=18, minute=0, tzinfo=timezone.utc)
    is_express = True if service_type == "Экспресс-подбор" else False

    new_order = Order(
        branch_id=manager.branch_id,
        client_id=client.id,
        manager_id=manager.id,
        car=car,
        detail=detail,
        paint_code=paint_code,
        category="Не указана",
        service_type=service_type,
        target_volume=target_volume,
        is_express=is_express,
        price=0.0,
        deadline_at=deadline_dt,
        manager_comment=manager_comment
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


@app.get("/order/{order_id}")
def view_order(request: Request, order_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        return RedirectResponse(url="/dashboard", status_code=303)

    user_role = user.role.lower() if user.role else ""

    if user_role == "колорист":
        return templates.TemplateResponse(
            request=request,
            name="colorist_order.html",
            context={"order": order}
        )
    elif user_role == "директор":
        return templates.TemplateResponse(
            request=request,
            name="director_order_detail.html",
            context={"order": order}
        )
    else:
        return templates.TemplateResponse(
            request=request,
            name="order_detail.html",
            context={"order": order}
        )


@app.post("/order/{order_id}/status")
def update_order_status(
        request: Request,
        order_id: int,
        new_status: str = Form(...),
        actual_volume: float = Form(None),
        db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    order = db.query(Order).filter(Order.id == order_id).first()
    if order:
        if user.role and user.role.lower() == "колорист":
            order.colorist_id = user.id

        if new_status == "В работе" and order.service_type in ["Подбор", "Экспресс-подбор"]:
            if not order.photo_detail:
                return HTMLResponse(f"""
                <div style="padding: 40px; text-align: center;">
                    <h2 style="color: #e74c3c;">Ошибка: Нет фото детали до работы!</h2>
                    <p style="font-size: 16px;">Менеджер не загрузил фото образца при оформлении.</p>
                    <button onclick="window.history.back()" style="padding: 10px 20px;">Назад</button>
                </div>
                """)

        if new_status == "Готово":
            if order.service_type in ["Подбор", "Экспресс-подбор"]:
                if not order.photo_scales or not order.photo_after:
                    return HTMLResponse(f"""
                    <div style="font-family: Arial, sans-serif; padding: 40px; text-align: center;">
                        <h2 style="color: #e74c3c;">Ошибка: Отсутствует фотоконтроль!</h2>
                        <p style="font-size: 16px; color: #2c3e50; max-width: 500px; margin: 0 auto;">
                            Для услуги «{order.service_type}» обязательно загрузите фотографию <b>краски на весах</b> и <b>детали после работы</b>.
                        </p>
                        <br><br>
                        <button onclick="window.history.back()" style="background: #3498db; color: white; padding: 10px 20px; border: none; border-radius: 5px; font-weight: bold; cursor: pointer;">← Вернуться к заказу</button>
                    </div>
                    """)
            else:
                if not order.photo_scales:
                    return HTMLResponse(f"""
                    <div style="font-family: Arial, sans-serif; padding: 40px; text-align: center;">
                        <h2 style="color: #e74c3c;">Ошибка: Отсутствует фотоконтроль!</h2>
                        <p style="font-size: 16px; color: #2c3e50; max-width: 500px; margin: 0 auto;">
                            Для услуги «{order.service_type}» обязательно загрузите фотографию <b>краски на весах</b>.
                        </p>
                        <br><br>
                        <button onclick="window.history.back()" style="background: #3498db; color: white; padding: 10px 20px; border: none; border-radius: 5px; font-weight: bold; cursor: pointer;">← Вернуться к заказу</button>
                    </div>
                    """)

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

    if new_status == "Готово":
        return RedirectResponse(url="/colorist", status_code=303)

    return RedirectResponse(url=f"/order/{order_id}", status_code=303)


@app.post("/order/{order_id}/upload")
def upload_photo(
        request: Request,
        order_id: int,
        photo_type: str = Form(...),
        file: UploadFile = File(...),
        db: Session = Depends(get_db)
):
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


@app.post("/order/{order_id}/recipe")
def add_recipe_item(
        request: Request,
        order_id: int,
        category: str = Form(...),
        toner_name: str = Form(...),
        weight: float = Form(...),
        db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    order = db.query(Order).filter(Order.id == order_id).first()
    if order:
        db.add(RecipeItem(order_id=order.id, category=category, toner_name=toner_name, weight=weight))
        db.commit()
    return RedirectResponse(url=f"/order/{order_id}", status_code=303)


@app.post("/order/{order_id}/recipe/{item_id}/delete")
def delete_recipe_item(
        request: Request,
        order_id: int,
        item_id: int,
        db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    item = db.query(RecipeItem).filter(RecipeItem.id == item_id, RecipeItem.order_id == order_id).first()
    if item:
        db.delete(item)
        db.commit()
    return RedirectResponse(url=f"/order/{order_id}", status_code=303)


@app.post("/order/{order_id}/finance")
def update_order_finance(
        request: Request,
        order_id: int,
        price: str = Form("0"),
        is_paid: str = Form(None),
        db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)

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


@app.get("/order/{order_id}/print")
def print_order(request: Request, order_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        return RedirectResponse(url="/dashboard", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="print_order.html",
        context={"order": order}
    )


@app.get("/client/{client_id}")
def view_client(request: Request, client_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(request=request, name="client_detail.html", context={"client": client})


# ==========================================
# БЛОК ДИРЕКТОРА
# ==========================================

@app.get("/director")
def director_dashboard(request: Request, branch_id: Optional[str] = None, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    if not user.role or user.role.lower() != "директор":
        return RedirectResponse(url="/dashboard", status_code=303)

    branches = db.query(Branch).all()
    query = db.query(Order).order_by(Order.created_at.desc())

    shifts_query = (
        db.query(Shift)
        .join(User)
        .filter(Shift.end_time == None)
        .order_by(Shift.start_time.desc())
    )

    current_branch = None

    if branch_id and branch_id.isdigit():
        b_id = int(branch_id)
        query = query.filter(Order.branch_id == b_id)
        shifts_query = shifts_query.filter(Shift.branch_id == b_id)
        current_branch = db.query(Branch).filter(Branch.id == b_id).first()

    all_orders = query.all()
    orders = [o for o in all_orders if not (o.status == "Выдано" and o.is_paid == True)]
    shifts = shifts_query.all()

    # Исправлено: теперь выручка корректно суммируется для заказов со статусом "Выдано" или полем is_paid == True
    total_revenue = sum(o.price for o in orders if o.price and (o.is_paid or o.status == "Выдано"))
    total_paint_volume = sum(o.actual_volume for o in orders if o.actual_volume is not None)
    total_reworks = sum(o.rework_count for o in orders)
    active_orders = len([o for o in orders if o.status not in ["Готово", "Выдано"]])

    return templates.TemplateResponse(
        request=request,
        name="director_dashboard.html",
        context={
            "username": user.username,
            "orders": orders,
            "shifts": shifts,
            "branches": branches,
            "current_branch": current_branch,
            "total_revenue": total_revenue,
            "total_paint_volume": round(total_paint_volume, 1),
            "total_reworks": total_reworks,
            "active_orders": active_orders
        }
    )


@app.get("/director/orders")
def director_active_orders(request: Request, branch_id: Optional[str] = None, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    if not user.role or user.role.lower() != "директор":
        return RedirectResponse(url="/dashboard", status_code=303)

    branches = db.query(Branch).all()
    query = db.query(Order).order_by(Order.created_at.desc())

    current_branch = None
    if branch_id and branch_id.isdigit():
        b_id = int(branch_id)
        query = query.filter(Order.branch_id == b_id)
        current_branch = db.query(Branch).filter(Branch.id == b_id).first()

    all_orders = query.all()
    active_orders = [o for o in all_orders if not (o.status == "Выдано" and o.is_paid == True)]

    return templates.TemplateResponse(
        request=request,
        name="director_orders.html",
        context={
            "orders": active_orders,
            "branches": branches,
            "current_branch": current_branch
        }
    )


@app.get("/director/branches")
def manage_branches(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    if not user.role or user.role.lower() != "директор":
        return RedirectResponse(url="/dashboard", status_code=303)

    branches = db.query(Branch).all()
    return templates.TemplateResponse(
        request=request,
        name="director_branches.html",
        context={"branches": branches}
    )


@app.get("/director/users")
def manage_users(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    if not user.role or user.role.lower() != "директор":
        return RedirectResponse(url="/dashboard", status_code=303)

    users = db.query(User).all()
    branches = db.query(Branch).all()
    return templates.TemplateResponse(
        request=request,
        name="director_users.html",
        context={"users": users, "branches": branches, "current_username": user.username}
    )


@app.get("/director/shifts/print")
def print_shifts_report(request: Request, branch_id: Optional[int] = None, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    if not user.role or user.role.lower() != "директор":
        return RedirectResponse(url="/dashboard", status_code=303)

    shifts_query = db.query(Shift).filter(Shift.end_time != None).order_by(Shift.start_time.desc())
    if branch_id:
        shifts_query = shifts_query.filter(Shift.branch_id == branch_id)

    shifts = shifts_query.all()

    return templates.TemplateResponse(
        request=request,
        name="shifts_report_print.html",
        context={"shifts": shifts}
    )


@app.post("/director/branch/add")
def add_branch(
        request: Request,
        name: str = Form(...),
        db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    if not user.role or user.role.lower() != "директор":
        return RedirectResponse(url="/dashboard", status_code=303)

    new_branch = Branch(name=name)
    db.add(new_branch)
    db.commit()

    return RedirectResponse(url="/director/branches?success=branch", status_code=303)


@app.post("/director/branch/delete/{branch_id}")
def delete_branch(
        request: Request,
        branch_id: int,
        db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    if not user.role or user.role.lower() != "директор":
        return RedirectResponse(url="/dashboard", status_code=303)

    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if branch:
        db.delete(branch)
        db.commit()

    return RedirectResponse(url="/director/branches?success=branch_delete", status_code=303)


@app.post("/director/user/add")
def add_user(
        request: Request,
        username_new: str = Form(...),
        role: str = Form(...),
        branch_id: int = Form(...),
        db: Session = Depends(get_db)
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/", status_code=303)

    if not current_user.role or current_user.role.lower() != "директор":
        return RedirectResponse(url="/dashboard", status_code=303)

    existing = db.query(User).filter(User.username == username_new).first()
    if existing:
        return HTMLResponse("Ошибка: Пользователь с таким логином уже существует.")

    employee_token = secrets.token_hex(16)

    new_user = User(
        username=username_new,
        password_hash=None,
        role=role,
        branch_id=branch_id,
        token=employee_token
    )
    db.add(new_user)
    db.commit()

    return RedirectResponse(url=f"/director/users?success=user&new_token={employee_token}&new_name={username_new}",
                            status_code=303)


@app.post("/director/user/delete/{user_id}")
def delete_user(
        request: Request,
        user_id: int,
        db: Session = Depends(get_db)
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/", status_code=303)

    if not current_user.role or current_user.role.lower() != "директор":
        return RedirectResponse(url="/dashboard", status_code=303)

    target_user = db.query(User).filter(User.id == user_id).first()
    if target_user:
        if target_user.id == current_user.id:
            return HTMLResponse("Ошибка: Нельзя удалить собственную учетную запись директора.")

        db.query(Shift).filter(Shift.user_id == user_id).delete()
        db.delete(target_user)
        db.commit()

    return RedirectResponse(url="/director/users?success=user_delete", status_code=303)


@app.post("/order/{order_id}/comment")
def update_order_comment(
        request: Request,
        order_id: int,
        comment_type: str = Form(...),
        comment_text: str = Form(...),
        db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    order = db.query(Order).filter(Order.id == order_id).first()
    if order:
        if comment_type == "manager":
            order.manager_comment = comment_text
        elif comment_type == "colorist":
            order.colorist_comment = comment_text
        db.commit()

    return RedirectResponse(url=f"/order/{order_id}", status_code=303)