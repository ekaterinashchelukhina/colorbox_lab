import ast
import json
import os
from datetime import datetime, timedelta
from io import BytesIO
from typing import List, Optional
from urllib.parse import quote
from passlib.context import CryptContext
from PIL import Image, UnidentifiedImageError
from fastapi import Request, Depends, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db, utc_now
from models import User, UserSession
from storage import storage

# Хэширование постоянного логин-токена сотрудника (main.py/routers/director.py) —
# bcrypt, тот же принцип, что для паролей: в базе не должно быть значения,
# по которому можно восстановить исходный токен при утечке.
_token_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Защита от подбора токена на /login — см. models.py (User.failed_login_attempts/locked_until).
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT = timedelta(minutes=15)


def hash_token(token: str) -> str:
    return _token_context.hash(token)


def verify_token(token: str, token_hash: str) -> bool:
    return _token_context.verify(token, token_hash)

# С запасом под фото с телефона до сжатия (после сжатия — единицы сотен КБ). Проверяется
# до PIL, чтобы гигантский файл не тратил память/CPU на попытку его распаковать.
MAX_UPLOAD_BYTES = 15 * 1024 * 1024

# Статус "мягкого удаления" заказа менеджером — заказ не удаляется физически, а уходит
# в архив с этим статусом. Общий модуль, т.к. на него ссылаются main.py/routers/*.py.
CANCELLED_STATUS = "Отменен"

# Инициализируем шаблоны здесь, чтобы использовать их во всех файлах
templates = Jinja2Templates(directory="templates")


def asset_version(rel_path: str) -> int:
    """mtime статического файла — используется в шаблонах как ?v=... у ссылок на
    static/css/*.css и static/js/*.js, чтобы браузер не отдавал закэшированную версию
    после правок вёрстки (без этого URL файла не менялся годами, и правки визуально
    "не доезжали" до пользователя без ручного сброса кэша)."""
    try:
        return int(os.path.getmtime(rel_path))
    except OSError:
        return 0


templates.env.globals["asset_version"] = asset_version


class InvalidImageError(Exception):
    """Загруженный файл не удалось прочитать как изображение (не картинка, битый файл,
    превышен размер и т.п.)."""


def _read_and_validate_size(file: UploadFile) -> bytes:
    data = file.file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise InvalidImageError(
            f"Файл '{file.filename}' слишком большой (максимум {MAX_UPLOAD_BYTES // (1024 * 1024)} МБ)."
        )
    return data


def _compress_image(data: bytes, filename: str) -> bytes:
    """Сжимает изображение и возвращает готовые JPEG-байты. Не занимается сохранением —
    куда положить байты (диск сегодня, S3 в будущем), решает storage.py."""
    try:
        img = Image.open(BytesIO(data))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        max_width = 1280
        if img.width > max_width:
            ratio = max_width / float(img.width)
            new_height = int(float(img.height) * float(ratio))
            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        img.save(buffer, "JPEG", quality=85, optimize=True)
        return buffer.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as e:
        raise InvalidImageError(f"Файл '{filename}' повреждён или не является изображением.") from e


def save_order_photo(file: UploadFile, key: str) -> str:
    """Сжимает и сохраняет фото заказа под заданным ключом (имя файла в хранилище),
    возвращает URL для записи в БД. Бросает InvalidImageError на нечитаемый/слишком
    большой файл."""
    data = _read_and_validate_size(file)
    jpeg_bytes = _compress_image(data, file.filename)
    return storage.save(key, jpeg_bytes)


def save_uploaded_photos(photos: List[UploadFile], user_id: int, tag: str) -> List[str]:
    """Сжимает и сохраняет набор фото смены, возвращает список URL.
    Бросает InvalidImageError, если хоть один файл не удалось прочитать как изображение."""
    saved_urls = []
    for photo in photos:
        if photo.filename:
            key = f"{user_id}_{tag}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.jpg"
            saved_urls.append(save_order_photo(photo, key))
    return saved_urls

def parse_photo_list(photo_data) -> List[str]:
    """Распаковывает поле с фото смены (JSON-список, python-repr или одиночный путь) в список URL."""
    if not photo_data:
        return []
    if isinstance(photo_data, list):
        return photo_data
    if isinstance(photo_data, str):
        try:
            parsed = json.loads(photo_data)
            return parsed if isinstance(parsed, list) else [str(parsed)]
        except json.JSONDecodeError:
            pass
        try:
            parsed = ast.literal_eval(photo_data)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
        return [photo_data]
    return []


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """Ищет пользователя по сессионному токену из cookie. Токен без действующей
    (непросроченной) записи в user_sessions считается недействительным — как будто
    пользователь не входил."""
    session_token = request.cookies.get("access_token")
    if not session_token:
        return None
    session = db.query(UserSession).filter(
        UserSession.token == session_token,
        UserSession.expires_at > utc_now()
    ).first()
    if not session:
        return None
    return db.query(User).filter(User.id == session.user_id).first()


class RedirectException(Exception):
    """Поднимается зависимостями авторизации, перехватывается обработчиком в main.py."""
    def __init__(self, url: str):
        self.url = url


def error_redirect(url: str, message: str) -> RedirectResponse:
    """Редирект с текстом ошибки в query-параметре ?error=... вместо отдельной страницы
    с одним <h2>. Страница-получатель (base.html/colorist_order.html подключают
    static/js/toast.js) на загрузке читает этот параметр, показывает всплывающую
    подсказку и сама убирает его из адресной строки — так что и refresh не покажет
    её повторно, и пользователь не теряет то, что уже было на экране."""
    separator = "&" if "?" in url else "?"
    return RedirectResponse(url=f"{url}{separator}error={quote(message)}", status_code=303)


def user_has_role(user: Optional[User], role_name: str) -> bool:
    """Точное сравнение роли пользователя без учёта регистра/пробелов, устойчиво к None.
    Единая точка сравнения вместо разбросанных по роутерам `user.role.lower() != "..."`."""
    return bool(user and user.role and user.role.strip().lower() == role_name.lower())


def display_role(user: Optional[User]) -> str:
    """Роль в форме для отображения и сравнения с шаблонами ('Директор', 'Менеджер', ...)."""
    return user.role.capitalize() if user and user.role else ""


def require_login(request: Request, db: Session = Depends(get_db)) -> User:
    """Требует авторизованного пользователя. Не проходит -> редирект на '/', как раньше."""
    user = get_current_user(request, db)
    if not user:
        raise RedirectException("/")
    return user


def require_director(request: Request, db: Session = Depends(get_db)) -> User:
    """Требует пользователя с ролью 'директор'. Не проходит -> редирект на '/'."""
    user = get_current_user(request, db)
    if not user_has_role(user, "директор"):
        raise RedirectException("/")
    return user


def require_director_page(request: Request, db: Session = Depends(get_db)) -> User:
    """Как require_director, но авторизованного пользователя с чужой ролью отправляет не на
    логин, а на его собственный '/dashboard' (тот сам разберётся, куда вести). Для страниц,
    до которых можно дойти только из уже вошедшего в систему интерфейса."""
    user = get_current_user(request, db)
    if not user:
        raise RedirectException("/")
    if not user_has_role(user, "директор"):
        raise RedirectException("/dashboard")
    return user


def get_in_branch_or_none(db: Session, model, record_id: int, user: User):
    """Запись модели (Order/Client — обе с колонкой branch_id) по id, но только если она
    в филиале пользователя (директор видит все филиалы). Иначе None — как будто записи не
    существует, чтобы не раскрывать данные чужого филиала по угадываемому id."""
    record = db.query(model).filter(model.id == record_id).first()
    if not record:
        return None
    if user_has_role(user, "директор") or record.branch_id == user.branch_id:
        return record
    return None


def scope_query_to_branch(query, model, user: User, branch_id_param=None):
    """Ограничивает query по филиалу: директор видит все филиалы (или выбранный через
    branch_id_param), остальные роли — только свой филиал. Единая точка для правила
    изоляции данных между филиалами, чтобы не дублировать if/else в каждом роуте."""
    if user_has_role(user, "директор"):
        branch_id = parse_optional_id(branch_id_param)
        if branch_id is not None:
            return query.filter(model.branch_id == branch_id)
        return query
    return query.filter(model.branch_id == user.branch_id)


def parse_optional_id(value) -> Optional[int]:
    """Разбирает необязательный числовой id из query-параметра (строка, число или None) в int,
    либо None, если значения нет или это не число. Проверка через `is None`/пустую строку,
    а не через truthiness — id=0 тоже валидный id и не должен трактоваться как "нет фильтра"."""
    if value is None or str(value) == "":
        return None
    if str(value).isdigit():
        return int(value)
    return None


def apply_date_range_filter(query, column, date_from: Optional[str], date_to: Optional[str]):
    """Фильтрует query по колонке-дате в диапазоне [date_from, date_to] (формат YYYY-MM-DD,
    date_to включительно — до конца суток). Некорректные/пустые даты молча игнорируются."""
    if date_from:
        try:
            query = query.filter(column >= datetime.strptime(date_from, "%Y-%m-%d"))
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            query = query.filter(column <= dt_to)
        except ValueError:
            pass
    return query


def paginate_query(query, page: int = 1, page_size: int = 50):
    """Постранично отдаёт результаты query. Возвращает (записи, номер_страницы,
    всего_страниц, всего_записей). Номер страницы приводится к допустимому диапазону."""
    total = query.count()
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return items, page, total_pages, total