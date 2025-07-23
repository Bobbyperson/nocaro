from sqlalchemy import Boolean, Column, DateTime, Integer, String

from . import Base


class User_Achievements(Base):
    __tablename__ = "user_achievements"

    user_id = Column(Integer, nullable=False, primary_key=True)
    achievement_id = Column(String, nullable=False, primary_key=True)
    achieved = Column(Boolean, nullable=False, default=False)
    progress = Column(Integer, nullable=False, default=0)
    achieved_at = Column(DateTime, nullable=False)
