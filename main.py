import os
import shutil
from datetime import datetime, timezone

from fastapi import FastAPI, Request, Form, Depends, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from database import get_db
from models import Base, Order, User, Client, Branch, RecipeItem

app = FastAPI(title="Colorist CRM")

os.makedirs("static/uploads", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@app.get("/")
def read_root(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")


@app.post("/login")
def login(
        username: str = Form(...),
        password: str = Form(...),
        db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.username == username).first()

    if not user or not pwd_context.verify(password, user.password_hash):
        return HTMLResponse("Ошибка: Неверный логин или пароль")

    response = HTMLResponse()

    if user.role and user.role.lower() == "колорист":
        response.headers["HX-Redirect"] = "/colorist"
    else:
        response.headers["HX-Redirect"] = "/dashboard"

    response.set_cookie(key="username", value=user.username)
    return response


@app.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    username = request.cookies.get("username")
    if not username:
        return RedirectResponse(url="/")

    user = db.query(User).filter(User.username == username).first()

    if user.role and user.role.lower() == "колорист":
        return RedirectResponse(url="/colorist", status_code=303)

    orders = db.query(Order).filter(Order.branch_id == user.branch_id).all()

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "username": username,
            "orders": orders
        }
    )


@app.get("/colorist")
def colorist_dashboard(request: Request, db: Session = Depends(get_db)):
    username = request.cookies.get("username")
    if not username:
        return RedirectResponse(url="/")

    user = db.query(User).filter(User.username == username).first()

    orders = db.query(Order).filter(
        Order.branch_id == user.branch_id,
        Order.status != "Выдано"
    ).order_by(
        Order.is_express.desc(),
        Order.rework_count.desc(),
        Order.created_at.asc()
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="colorist_dashboard.html",
        context={
            "username": username,
            "orders": orders
        }
    )


@app.get("/logout")
def logout():
    response = RedirectResponse(url="/")
    response.delete_cookie("username")
    return response


@app.get("/new-order")
def show_new_order_form(request: Request):
    username = request.cookies.get("username")
    if not username:
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
        file: UploadFile = File(None), # Ловим файл из формы
        db: Session = Depends(get_db)
):
    username = request.cookies.get("username")
    if not username:
        return RedirectResponse(url="/", status_code=303)

    # 1. СТРОГАЯ ПРОВЕРКА ФОТО ДЕТАЛИ
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

    manager = db.query(User).filter(User.username == username).first()
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
        deadline_at=deadline_dt
    )
    db.add(new_order)
    db.commit()
    db.refresh(new_order) # Получаем ID только что созданного заказа

    # 2. СОХРАНЯЕМ ФОТОГРАФИЮ, ЕСЛИ ОНА ЕСТЬ
    if file and file.filename:
        file_extension = file.filename.split(".")[-1]
        file_path = f"static/uploads/order_{new_order.id}_detail.{file_extension}"
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        new_order.photo_detail = f"/{file_path}"
        db.commit()

    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/order/{order_id}")
def view_order(request: Request, order_id: int, db: Session = Depends(get_db)):
    username = request.cookies.get("username")
    if not username:
        return RedirectResponse(url="/", status_code=303)

    user = db.query(User).filter(User.username == username).first()
    order = db.query(Order).filter(Order.id == order_id).first()

    if not order:
        return RedirectResponse(url="/dashboard", status_code=303)

    if user.role and user.role.lower() == "колорист":
        return templates.TemplateResponse(
            request=request,
            name="colorist_order.html",
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
    username = request.cookies.get("username")
    if not username:
        return RedirectResponse(url="/", status_code=303)

    order = db.query(Order).filter(Order.id == order_id).first()
    if order:

        # 1. Валидация фото от Менеджера при приемке (Только для подборов)
        if new_status == "В работе" and order.service_type in ["Подбор", "Экспресс-подбор"]:
            if not order.photo_detail:
                return HTMLResponse(f"""
                <div style="padding: 40px; text-align: center;">
                    <h2 style="color: #e74c3c;">Ошибка: Нет фото детали до работы!</h2>
                    <p style="font-size: 16px;">Менеджер не загрузил фото образца при оформлении.</p>
                    <button onclick="window.history.back()" style="padding: 10px 20px;">Назад</button>
                </div>
                """)

        # 2. Валидация фото от Колориста при сдаче (Разграничение логики)
        if new_status == "Готово":
            if order.service_type in ["Подбор", "Экспресс-подбор"]:
                # Для подборов требуем и весы, и результат на детали
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
                # Для слива по коду и банок требуем ТОЛЬКО весы
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

        # 3. Обработка статусов и переделок
        if new_status == "Переделка":
            order.status = "В очереди"
            order.rework_count += 1
        else:
            order.status = new_status

        if new_status == "Готово" and actual_volume is not None:
            order.actual_volume = actual_volume

        db.commit()

    return RedirectResponse(url=f"/order/{order_id}", status_code=303)

@app.post("/order/{order_id}/upload")
def upload_photo(request: Request, order_id: int, photo_type: str = Form(...), file: UploadFile = File(...),
                 db: Session = Depends(get_db)):
    if not request.cookies.get("username"): return RedirectResponse(url="/", status_code=303)
    order = db.query(Order).filter(Order.id == order_id).first()

    if order and file and file.filename:
        file_extension = file.filename.split(".")[-1]
        file_path = f"static/uploads/order_{order_id}_{photo_type}.{file_extension}"
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        if photo_type == "detail":
            order.photo_detail = f"/{file_path}"
        elif photo_type == "scales":
            order.photo_scales = f"/{file_path}"
        elif photo_type == "after":
            order.photo_after = f"/{file_path}"  # Сохраняем новое фото

        db.commit()
    return RedirectResponse(url=f"/order/{order_id}", status_code=303)

@app.post("/order/{order_id}/recipe")
def add_recipe_item(request: Request, order_id: int, category: str = Form(...), toner_name: str = Form(...),
                    weight: float = Form(...), db: Session = Depends(get_db)):
    if not request.cookies.get("username"): return RedirectResponse(url="/", status_code=303)
    order = db.query(Order).filter(Order.id == order_id).first()
    if order:
        db.add(RecipeItem(order_id=order.id, category=category, toner_name=toner_name, weight=weight))
        db.commit()
    return RedirectResponse(url=f"/order/{order_id}", status_code=303)


@app.post("/order/{order_id}/recipe/{item_id}/delete")
def delete_recipe_item(request: Request, order_id: int, item_id: int, db: Session = Depends(get_db)):
    if not request.cookies.get("username"): return RedirectResponse(url="/", status_code=303)
    item = db.query(RecipeItem).filter(RecipeItem.id == item_id, RecipeItem.order_id == order_id).first()
    if item:
        db.delete(item)
        db.commit()
    return RedirectResponse(url=f"/order/{order_id}", status_code=303)


@app.post("/order/{order_id}/finance")
def update_order_finance(request: Request, order_id: int, price: float = Form(0.0), is_paid: str = Form(None),
                         db: Session = Depends(get_db)):
    if not request.cookies.get("username"): return RedirectResponse(url="/", status_code=303)
    order = db.query(Order).filter(Order.id == order_id).first()
    if order:
        order.price = price
        order.is_paid = (is_paid == "on")
        db.commit()
    return RedirectResponse(url=f"/order/{order_id}", status_code=303)


@app.post("/order/{order_id}/upload")
def upload_photo(request: Request, order_id: int, photo_type: str = Form(...), file: UploadFile = File(...),
                 db: Session = Depends(get_db)):
    if not request.cookies.get("username"): return RedirectResponse(url="/", status_code=303)
    order = db.query(Order).filter(Order.id == order_id).first()
    if order:
        file_extension = file.filename.split(".")[-1]
        file_path = f"static/uploads/order_{order_id}_{photo_type}.{file_extension}"
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        if photo_type == "detail":
            order.photo_detail = f"/{file_path}"
        elif photo_type == "scales":
            order.photo_scales = f"/{file_path}"
        db.commit()
    return RedirectResponse(url=f"/order/{order_id}", status_code=303)


@app.get("/order/{order_id}/print")
def print_order(request: Request, order_id: int, db: Session = Depends(get_db)):
    username = request.cookies.get("username")
    if not username:
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
    if not request.cookies.get("username"): return RedirectResponse(url="/", status_code=303)
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client: return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(request=request, name="client_detail.html", context={"client": client})