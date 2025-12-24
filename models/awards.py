from sqlalchemy import Column, String

from . import Base


class AwardUsers(Base):
    __tablename__ = "award_users"

    user_id = Column(String, primary_key=True)
