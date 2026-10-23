from sqlalchemy import Boolean, Column, DateTime, Enum, Integer, String, func, text

from app.core.db.databases import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True)
    hashed_password = Column(String(255))
    name = Column(String(20))
    phone_number = Column(String(20), unique=True)
    gender = Column(Enum("male", "female", name="gender"), nullable=False)
    department = Column(
        Enum("radiology", "administration", name="department"), nullable=False
    )
    role = Column(Enum("admin", "doctor", "user", name="role"), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("1"))
    created_at = Column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    updated_at = Column(DateTime, onupdate=func.current_timestamp())