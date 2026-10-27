from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from .database import get_db
from .core.permissions import get_current_user
from .models.user import User

def get_pagination(page: int = 1, page_size: int = 20):
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 20
    if page_size > 100:
        page_size = 100
    return {"page": page, "page_size": page_size, "offset": (page-1)*page_size}
