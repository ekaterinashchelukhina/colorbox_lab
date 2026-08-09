import os
import secrets
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import or_
from sqlalchemy.orm import Session

# Импорты базы данных и утилит
from database import get_db, sync_schema
from models import User, Order, Shift
from utils import templates, RedirectException, require_login, utc_now, user_has_role, CANCELLED_STATUS
from storage import UPLOAD_DIR

SESSION_LIFETIME = timedelta(days=30)

# Импорт наших новых роутеров
from routers import director, colorist, manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Подтягивает схему БД под текущие модели (новые таблицы/колонки),
    # чтобы деплой без ручной миграции не ронял приложение при расхождении схемы.
    sync_schema()
    yield


app = FastAPI(title="Colorist CRM", lifespan=lifespan)

# CSS/JS — обычная публичная статика. Фото заказов/смен (static/uploads/) сюда
# намеренно не входят: они отдаются через serve_uploaded_photo ниже, с проверкой прав,
# а не голым маунтом — см. пояснение там.
app.mount("/static/css", StaticFiles(directory="static/css"), name="static_css")
app.mount("/static/js", StaticFiles(directory="static/js"), name="static_js")

# Регистрируем роутеры из других файлов
app.include_router(director.router)
app.include_router(colorist.router)
app.include_router(manager.router)


@app.exception_handler(RedirectException)
def redirect_exception_handler(request: Request, exc: RedirectException):
    return RedirectResponse(url=exc.url, status_code=303)


# Колонки заказа, где может лежать URL вида "/static/uploads/<filename>".
_ORDER_PHOTO_COLUMNS = [
    Order.photo_detail, Order.photo_scales, Order.photo_after, Order.recipe_photo,
    Order.rework_photo_scales, Order.rework_photo_after, Order.rework_photo_test,
]


@app.get("/static/uploads/{filename}")
def serve_uploaded_photo(filename: str, db: Session = Depends(get_db), user: User = Depends(require_login)):
    """Отдаёт фото заказа/смены только тому, кому разрешено видеть филиал, где оно
    сделано (директору — любое). Без этого голый StaticFiles-маунт на static/uploads/
    отдавал бы файл всем подряд по URL: имена файлов заказов детерминированы
    (order_{id}_{type}.jpg) с последовательным id — фото легко перебрать без логина.
    """
    # {filename} у FastAPI и так не матчит "/" в пути, но на случай будущих изменений
    # роута — явная страховка от выхода за пределы UPLOAD_DIR.
    filename = os.path.basename(filename)
    url = f"/static/uploads/{filename}"

    order = db.query(Order).filter(or_(*[col == url for col in _ORDER_PHOTO_COLUMNS])).first()
    if order and (user_has_role(user, "директор") or order.branch_id == user.branch_id):
        return _file_response_or_404(filename)

    # Фото смены хранятся списком в одной JSON-колонке (Shift.start_photos/end_photos),
    # а не отдельным полем на файл — сравниваем подстрокой.
    shift = db.query(Shift).filter(
        or_(Shift.start_photos.contains(filename), Shift.end_photos.contains(filename))
    ).first()
    if shift and (user_has_role(user, "директор") or shift.branch_id == user.branch_id):
        return _file_response_or_404(filename)

    # И "файл ни на что не сослался", и "сослался, но из чужого филиала" — один и тот
    # же 404, чтобы не подтверждать чужаку сам факт существования файла.
    raise HTTPException(status_code=404)


def _file_response_or_404(filename: str) -> FileResponse:
    path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404)
    return FileResponse(path)

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

    if user_has_role(user, "директор"):
        redirect_url = "/director"
    elif user_has_role(user, "колорист"):
        redirect_url = "/colorist"
    else:
        redirect_url = "/dashboard"

    # Постоянный логин-токен (token) — пароль сотрудника, не меняется.
    # В cookie кладём отдельный сессионный токен с ограниченным сроком действия,
    # выдаваемый заново при каждом входе.
    user.session_token = secrets.token_hex(32)
    user.session_expires_at = utc_now() + SESSION_LIFETIME
    db.commit()

    response = RedirectResponse(url=redirect_url, status_code=303)
    # secure зависит от схемы запроса: жёстко включать его нельзя, иначе логин
    # ломается при локальной разработке по http; за HTTPS-прокси (продакшн) req
    # приходит уже как https, и secure включается автоматически.
    response.set_cookie(key="access_token", value=user.session_token, httponly=True,
                        max_age=int(SESSION_LIFETIME.total_seconds()),
                        samesite="lax", secure=request.url.scheme == "https")
    return response

@app.get("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    session_token = request.cookies.get("access_token")
    if session_token:
        user = db.query(User).filter(User.session_token == session_token).first()
        if user:
            user.session_token = None
            user.session_expires_at = None
            db.commit()

    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("access_token", samesite="lax", secure=request.url.scheme == "https")
    return response

@app.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db), user: User = Depends(require_login)):
    if user_has_role(user, "колорист"):
        return RedirectResponse(url="/colorist", status_code=303)
    if user_has_role(user, "директор"):
        return RedirectResponse(url="/director", status_code=303)

    orders = db.query(Order).filter(
        Order.branch_id == user.branch_id, Order.status.notin_(["Выдано", CANCELLED_STATUS])
    ).order_by(Order.created_at.desc()).all()

    active_shift = db.query(Shift).filter(Shift.user_id == user.id, Shift.end_time == None).first()

    return templates.TemplateResponse(request=request, name="dashboard.html", context={
        "username": user.username,
        "orders": orders,
        "active_shift": active_shift
    })

