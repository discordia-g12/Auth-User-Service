from sqlalchemy import Column, String, ForeignKey
from app.db.base import Base
from sqlalchemy.orm import relationship

class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    username = Column(String, unique=True, index=True, nullable=False) 
    avatar_url = Column(String, nullable=True)
    bio = Column(String, nullable=True) 
    
    activity_status = Column(String, default="offline") 
    custom_status = Column(String, nullable=True)

    user = relationship("User", back_populates="profile")