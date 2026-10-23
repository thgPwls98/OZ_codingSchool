from sqlalchemy import Boolean, Column, Enum, Integer, String, text
from sqlalchemy.orm import relationship

from app.core.db.databases import Base
from app.core.db.models import TimestampMixin
from app.models.enums import GENDER_ENUM


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True)
    hashed_password = Column(String(255))
    name = Column(String(20))
    phone_number = Column(String(20), unique=True)
    gender = Column(GENDER_ENUM, nullable=False)
    department = Column(
        Enum("radiology", "administration", name="department"), nullable=False
    )
    role = Column(Enum("admin", "doctor", "user", name="role"), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("1"))
    xray_images = relationship("XrayImage", back_populates="uploader")