import ast
import json
import os
from datetime import datetime
from typing import List, Optional
from PIL import Image
from fastapi import Request, Depends, UploadFile
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from models import User

UPLOAD_DIR = "static/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Инициализируем шаблоны здесь, чтобы использовать их во всех файлах
templates = Jinja2Templates(directory="templates")

def compress_and_save_image(file: UploadFile, path: str):
    img = Image.open(file.file)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    max_width = 1280
    if img.width > max_width:
        ratio = max_width / float(img.width)
        new_height = int(float(img.height) * float(ratio))
        img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
    img.save(path, "JPEG", quality=85, optimize=True)

def save_uploaded_photos(photos: List[UploadFile], user_id: int, tag: str) -> List[str]:
    """Сжимает и сохраняет набор фото смены, возвращает список путей."""
    saved_files = []
    for photo in photos:
        if photo.filename:
            filename = f"{user_id}_{tag}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.jpg"
            file_path = os.path.join(UPLOAD_DIR, filename)
            compress_and_save_image(photo, file_path)
            saved_files.append(file_path.replace("\\", "/"))
    return saved_files

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
    token = request.cookies.get("access_token")
    if not token:
        return None
    return db.query(User).filter(User.token == token).first()


class RedirectException(Exception):
    """Поднимается зависимостями авторизации, перехватывается обработчиком в main.py."""
    def __init__(self, url: str):
        self.url = url


def require_login(request: Request, db: Session = Depends(get_db)) -> User:
    """Требует авторизованного пользователя. Не проходит -> редирект на '/', как раньше."""
    user = get_current_user(request, db)
    if not user:
        raise RedirectException("/")
    return user


def require_director(request: Request, db: Session = Depends(get_db)) -> User:
    """Требует пользователя с ролью 'директор'. Не проходит -> редирект на '/'."""
    user = get_current_user(request, db)
    if not user or not user.role or user.role.lower() != "директор":
        raise RedirectException("/")
    return user