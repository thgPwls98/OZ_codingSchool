from sqlalchemy import Boolean, Column, Integer, String, text
from sqlalchemy.orm import relationship

from app.core.db.databases import Base
from app.core.db.models import TimestampMixin
from app.models.enums import DEPARTMENT_ENUM, GENDER_ENUM, ROLE_ENUM, Role


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    name = Column(String(20), nullable=False)
    phone_number = Column(String(20), unique=True, nullable=False)
    gender = Column(GENDER_ENUM, nullable=False)
    department = Column(DEPARTMENT_ENUM, nullable=False)
    role = Column(
        ROLE_ENUM,
        nullable=False,
        default=Role.PENDING,
        server_default=Role.PENDING.value,
    )
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("1"))
    xray_images = relationship("XrayImage", back_populates="uploader")
