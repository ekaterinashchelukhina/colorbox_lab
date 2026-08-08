import os
from typing import Optional
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

def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    token = request.cookies.get("access_token")
    if not token:
        return None
    return db.query(User).filter(User.token == token).first()