from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import datetime, date, timedelta
import json
import dateparser
from openai import OpenAI
from ..database import get_db
from ..models import Task, User
from ..schemas import (
    TaskCreate, TaskUpdate, TaskOut,
    TaskParseRequest, TaskParseResponse,
    TaskDescribeRequest, TaskDescribeResponse,
    AIHintsResponse,
)
from ..auth import get_current_user
from ..config import settings

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

def llm():
    return OpenAI(base_url=settings.OLLAMA_BASE_URL, api_key="ollama")
@router.get("/", response_model=List[TaskOut])
def get_tasks(
    completed: Optional[bool] = None,
    subject_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Task).filter(Task.user_id == current_user.id)
    if completed is not None:
        q = q.filter(Task.is_completed == completed)
    if subject_id:
        q = q.filter(Task.subject_id == subject_id)
    if date_from:
        q = q.filter(Task.deadline >= date_from)
    if date_to:
        q = q.filter(Task.deadline <= date_to)

    return q.order_by(Task.deadline).all()
@router.get("/today", response_model=List[TaskOut])
def get_today_tasks(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    today = date.today()
    start = datetime.combine(today, datetime.min.time())
    end = datetime.combine(today, datetime.max.time())

    return (
        db.query(Task)
        .filter(Task.user_id == current_user.id, Task.deadline >= start, Task.deadline <= end)
        .order_by(Task.deadline)
        .all()
    )
@router.get("/week", response_model=List[TaskOut])
def get_week_tasks(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    today = date.today()
    start = datetime.combine(today, datetime.min.time())
    end = datetime.combine(today + timedelta(days=6), datetime.max.time())

    return (
        db.query(Task)
        .filter(Task.user_id == current_user.id, Task.deadline >= start, Task.deadline <= end)
        .order_by(Task.deadline)
        .all()
    )
@router.get("/stats/week")
def get_week_stats(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    today = date.today()

    days = []
    for i in range(0, 7):
        day = today + timedelta(days=i)
        start = datetime.combine(day, datetime.min.time())
        end = datetime.combine(day, datetime.max.time())
        tasks = (
            db.query(Task)
            .filter(Task.user_id == current_user.id, Task.deadline >= start, Task.deadline <= end, Task.is_completed == False)
            .all()
        )
        hours = sum(t.estimated_hours for t in tasks)
        days.append({
            "date": day.isoformat(),
            "day_name": ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"][day.weekday()],
            "total_hours": round(hours,1),
            "task_count": len(tasks),
            "is_overloaded": hours > 4,
        })

    total = db.query(Task).filter(Task.user_id == current_user.id).count()
    done = db.query(Task).filter(Task.user_id == current_user.id, Task.is_completed == True).count()
    return {
        "days": days,
        "total_tasks": total,
        "completed_tasks": done,
        "overloaded_days": sum(1 for d in days if d["is_overloaded"]),
    }
@router.get("/stats/subjects")
def get_subject_stats(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tasks = db.query(Task).filter(Task.user_id == current_user.id).all()

    stats = {}
    for task in tasks:
        name = task.subject.name if task.subject else "Без предмета"
        color = task.subject.color if task.subject else "#95A5A6"
        if name not in stats:
            stats[name] = {"name": name, "color": color, "total": 0, "completed": 0, "hours": 0}
        stats[name]["total"] += 1
        stats[name]["hours"] += task.estimated_hours
        if task.is_completed:
            stats[name]["completed"] += 1

    return list(stats.values())
@router.post("/parse", response_model=TaskParseResponse)
def parse_task_text(data: TaskParseRequest, current_user: User = Depends(get_current_user)):
    prompt = (
        'Разбери описание учебной задачи и верни JSON с полями: '
        'title (краткое название, строка), description (детали или null), '
        'task_type (одно из: homework/project/test/olympiad/section/other), '
        'priority (low/medium/high), estimated_hours (число 0.5–12), '
        f'deadline_text (дедлайн исходной фразой или null). Текст: "{data.text}"'
    )
    resp = llm().chat.completions.create(
        model=settings.AI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        max_tokens=512,
    )

    try:
        parsed = json.loads(resp.choices[0].message.content)
    except Exception:
        parsed = {"title": data.text}

    deadline = None
    if parsed.get("deadline_text"):
        dt = dateparser.parse(
            parsed["deadline_text"],
            languages=["ru", "en"],
            settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": False},
        )
        if dt:
            deadline = dt.isoformat()

    return TaskParseResponse(
        title=parsed.get("title"),
        description=parsed.get("description"),
        task_type=parsed.get("task_type", "homework"),
        priority=parsed.get("priority", "medium"),
        estimated_hours=float(parsed.get("estimated_hours") or 1.0),
        deadline=deadline,
    )
@router.post("/describe", response_model=TaskDescribeResponse)
def describe_task(data: TaskDescribeRequest, current_user: User = Depends(get_current_user)):
    diff_map = {"easy": "лёгкая", "medium": "средняя", "hard": "сложная"}

    parts = [f'Задача: "{data.title}"']
    if data.task_type:
        parts.append(f"тип: {data.task_type}")
    if data.subject_name:
        parts.append(f"предмет: {data.subject_name}")
    if data.difficulty:
        parts.append(f"сложность: {diff_map.get(data.difficulty, data.difficulty)}")

    context = ", ".join(parts)
    prompt = (
        "Ты помощник школьника. Напиши краткое описание учебной задачи (2–3 предложения): "
        "что конкретно нужно сделать, на что обратить внимание. "
        f"{context}. Верни JSON: {{\"description\": \"...\"}}"
    )
    resp = llm().chat.completions.create(
        model=settings.AI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        max_tokens=256,
    )
    result = json.loads(resp.choices[0].message.content)
    return TaskDescribeResponse(description=result.get("description", ""))
@router.get("/hints", response_model=AIHintsResponse)
def get_ai_hints(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    now = datetime.utcnow()
    week_ahead = now + timedelta(days=7)
    week_ago = now - timedelta(days=7)

    active = db.query(Task).filter(Task.user_id == current_user.id, Task.is_completed == False).all()
    overdue = [t for t in active if t.deadline < now]
    upcoming = [t for t in active if now <= t.deadline <= week_ahead]
    done_count = db.query(Task).filter(
        Task.user_id == current_user.id,
        Task.is_completed == True,
        Task.completed_at >= week_ago,
    ).count()

    if not active and not done_count:
        return AIHintsResponse(hints=["Добавь первую задачу, чтобы получить персональные советы!"])

    lines = []
    if overdue:
        lines.append(f"Просроченных задач: {len(overdue)} ({', '.join(t.title for t in overdue[:3])})")
    if upcoming:
        total_h = round(sum(t.estimated_hours for t in upcoming),1)
        lines.append(f"Задач на 7 дней: {len(upcoming)}, суммарно {total_h} ч")

        day_h = {}
        for t in upcoming:
            d = t.deadline.date()
            day_h[d] = day_h.get(d, 0) + t.estimated_hours
        heavy = [(d, round(h,1)) for d, h in day_h.items() if h > 4]
        if heavy:
            lines.append("Перегруженные дни: " + ", ".join(f"{d.strftime('%d.%m')} ({h}ч)" for d, h in heavy))
    lines.append(f"Выполнено за последние 7 дней: {done_count} задач")

    prompt = (
        "Ты умный помощник школьника. На основе данных о нагрузке дай 3 конкретных совета "
        "(каждый — одно предложение, начинается с глагола действия, на русском языке).\n"
        "Данные:\n" + "\n".join(lines) + "\n"
        'Верни JSON: {"hints": ["совет1", "совет2", "совет3"]}'
    )
    resp = llm().chat.completions.create(
        model=settings.AI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        max_tokens=512,
    )
    result = json.loads(resp.choices[0].message.content)
    return AIHintsResponse(hints=result.get("hints", []))
@router.post("/", response_model=TaskOut, status_code=201)
def create_task(data: TaskCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task = Task(**data.model_dump(), user_id=current_user.id)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task
@router.put("/{task_id}", response_model=TaskOut)
def update_task(task_id: int, data: TaskUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == current_user.id).first()
    if not task:
        raise HTTPException(404, "Task not found")

    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(task, k, v)

    if data.is_completed is True and not task.completed_at:
        task.completed_at = datetime.utcnow()
    elif data.is_completed is False:
        task.completed_at = None

    db.commit()
    db.refresh(task)
    return task
@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == current_user.id).first()
    if not task:
        raise HTTPException(404, "Task not found")

    db.delete(task)
    db.commit()