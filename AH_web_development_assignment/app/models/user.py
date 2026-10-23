# app/models/user.py (추가)
medical_records: Mapped[list["MedicalRecord"]] = relationship(
    back_populates="user",
    cascade="all, delete-orphan",
    passive_deletes=True,
)
