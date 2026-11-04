from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Float, Text, Enum, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base
import enum

class PriorityLevel(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"

class TaskType(str, enum.Enum):
    homework = "homework"
    project = "project"
    test = "test"
    olympiad = "olympiad"
    section = "section"
    other = "other"

class DifficultyLevel(str, enum.Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    notify_day = Column(Boolean, default=True, nullable=False)
    notify_urgent = Column(Boolean, default=False, nullable=False)
    notify_overload = Column(Boolean, default=True, nullable=False)
    notify_morning = Column(Boolean, default=False, nullable=False)
    overload_threshold = Column(Float, default=4.0, nullable=False)
    last_morning_notified = Column(DateTime(timezone=True), nullable=True)
    last_overload_notified = Column(DateTime(timezone=True), nullable=True)

    tasks = relationship("Task", back_populates="owner", cascade="all, delete-orphan")
    subjects = relationship("Subject", back_populates="owner", cascade="all, delete-orphan")
    push_subscriptions = relationship("PushSubscription", back_populates="user", cascade="all, delete-orphan")

class Subject(Base):
    __tablename__ = "subjects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    color = Column(String(7), default="#4A90D9")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner = relationship("User", back_populates="subjects")
    tasks = relationship("Task", back_populates="subject")

class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    task_type = Column(Enum(TaskType), default=TaskType.homework)
    difficulty = Column(Enum(DifficultyLevel), default=DifficultyLevel.medium)
    deadline = Column(DateTime(timezone=True), nullable=False)
    estimated_hours = Column(Float, default=1.0)
    is_completed = Column(Boolean, default=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    notified_day_at = Column(DateTime(timezone=True), nullable=True)
    notified_urgent_at = Column(DateTime(timezone=True), nullable=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=True)

    owner = relationship("User", back_populates="tasks")
    subject = relationship("Subject", back_populates="tasks")
    priority = Column(String(10), default="medium", nullable=False)

class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    author = relationship("User")

class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    __table_args__ = (UniqueConstraint("endpoint", name="uq_push_subscriptions_endpoint"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    endpoint = Column(Text, nullable=False)
    p256dh = Column(String(255), nullable=False)
    auth = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="push_subscriptions")