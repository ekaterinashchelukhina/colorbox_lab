from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

# Импорты базы данных и утилит
from database import get_db, sync_schema
from models import User, Order, Shift
from utils import templates, RedirectException, require_login

# Импорт наших новых роутеров
from routers import director, colorist, manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Подтягивает схему БД под текущие модели (новые таблицы/колонки),
    # чтобы деплой без ручной миграции не ронял приложение при расхождении схемы.
    sync_schema()
    yield


app = FastAPI(title="Colorist CRM", lifespan=lifespan)

# Подключаем статику
app.mount("/static", StaticFiles(directory="static"), name="static")

# Регистрируем роутеры из других файлов
app.include_router(director.router)
app.include_router(colorist.router)
app.include_router(manager.router)


@app.exception_handler(RedirectException)
def redirect_exception_handler(request: Request, exc: RedirectException):
    return RedirectResponse(url=exc.url, status_code=303)

# ==========================================
# Базовые маршруты (вход и главная)
# ==========================================

@app.get("/")
def read_root(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")

@app.post("/login")
def login(request: Request, username: str = Form(...), token: str = Form(...), db: Session = Depends(get_db)):
    clean_username = username.strip()
    clean_token = token.strip()
    user = db.query(User).filter(User.username == clean_username, User.token == clean_token).first()

    if not user:
        return templates.TemplateResponse(request=request, name="login.html", context={"error_message": "Неверный логин или токен доступа"})

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
def logout(request: Request):
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("access_token")
    return response

@app.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db), user: User = Depends(require_login)):
    if user.role and user.role.lower() == "колорист":
        return RedirectResponse(url="/colorist", status_code=303)
    if user.role and user.role.lower() == "директор":
        return RedirectResponse(url="/director", status_code=303)

    orders = db.query(Order).filter(
        Order.branch_id == user.branch_id, Order.status != "Выдано"
    ).order_by(Order.created_at.desc()).all()

    active_shift = db.query(Shift).filter(Shift.user_id == user.id, Shift.end_time == None).first()

    return templates.TemplateResponse(request=request, name="dashboard.html", context={
        "username": user.username,
        "orders": orders,
        "active_shift": active_shift
    })

