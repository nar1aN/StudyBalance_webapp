from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional
from datetime import datetime, date, timedelta
from pydantic import BaseModel
import json
import re
from openai import OpenAI

from ..database import get_db
from ..models import Task, User, Subject, Message
from ..auth import get_current_user
from ..config import settings

router = APIRouter(prefix="/api/chat", tags=["chat"])

histories = {}

def llm():
    return OpenAI(base_url=settings.OLLAMA_BASE_URL, api_key="ollama")
def build_context(user_id, db):
    now = datetime.now()
    today = now.date()
    wd = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

    active = (
        db.query(Task)
        .filter(Task.user_id == user_id, Task.is_completed == False)
        .order_by(Task.deadline)
        .all()
    )
    subjects = db.query(Subject).filter(Subject.user_id == user_id).all()

    lines = [f"Сейчас: {now.strftime('%d.%m.%Y %H:%M')}"]
    if subjects:
        lines.append("Предметы: " + ", ".join(s.name for s in subjects))

    lines.append("\nРасписание (следующие 7 дней):")
    for i in range(0, 7):
        day = today + timedelta(days=i)
        day_tasks = [t for t in active if t.deadline and t.deadline.date() == day]
        if not day_tasks:
            lines.append(f"  {wd[day.weekday()]} {day.strftime('%d.%m')}: свободно")
            continue

        total_h = sum(t.estimated_hours for t in day_tasks)
        flag = " [ПЕРЕГРУЗ]" if total_h > 4 else ""
        lines.append(f"  {wd[day.weekday()]} {day.strftime('%d.%m')}: {total_h:.1f}ч{flag}")
        for t in day_tasks:
            subj = t.subject.name if t.subject else "—"
            lines.append(
                f"    id={t.id} «{t.title}» {subj}, {t.estimated_hours}ч,"
                f" приоритет={t.priority}, дедлайн={t.deadline.strftime('%d.%m %H:%M')}"
            )

    overdue = [t for t in active if t.deadline and t.deadline < now]
    if overdue:
        lines.append(f"\nПросрочено: {len(overdue)} задач")
        for t in overdue[:4]:
            lines.append(f"  id={t.id} «{t.title}»")

    return "\n".join(lines)

system_prompt = (
    "Ты — AI-помощник школьника в приложении StudyBalance.\n"
    "Ты знаешь расписание пользователя и помогаешь ему не перегружаться (норма — не более 4 ч в день).\n\n"
    "Умеешь:\n"
    "- Отвечать на вопросы о расписании и задачах\n"
    "- Рекомендовать оптимальный день для новой задачи (смотри на свободные/незагруженные дни)\n"
    "- Создавать, изменять, переносить и удалять задачи по просьбе пользователя\n\n"
    "Если нужно изменить расписание, добавь в конец ответа блок действия (одним из трёх форматов):\n"
    '<action>{"type":"create_task","data":{"title":"...","deadline":"2025-01-15T23:59:00",'
    '"estimated_hours":2,"task_type":"homework","priority":"medium","subject_id":null}}</action>\n'
    "или\n"
    '<action>{"type":"update_task","task_id":5,"data":{"deadline":"2025-01-16T23:59:00"}}</action>\n'
    "или\n"
    '<action>{"type":"delete_task","task_id":5}</action>\n\n'
    "Отвечай кратко и дружелюбно на русском языке."
)

def get_action(text):
    m = re.search(r"<action>(.*?)</action>", text, re.DOTALL)
    if not m:
        return text, None

    try:
        action = json.loads(m.group(1).strip())
    except json.JSONDecodeError:
        return text, None

    clean = (text[: m.start()] + text[m.end():]).strip()
    return clean, action
#Выполняем то, что попросила модель
def do_action(action, user, db):
    t = action.get("type")

    if t == "create_task":
        data = action.get("data", {})
        try:
            dl = datetime.fromisoformat(data["deadline"]) if data.get("deadline") else datetime.now() + timedelta(days=1)
        except Exception:
            dl = datetime.now() + timedelta(days=1)

        task = Task(
            user_id=user.id,
            title=data.get("title", "Новая задача"),
            deadline=dl,
            estimated_hours=float(data.get("estimated_hours", 1.0)),
            task_type=data.get("task_type", "homework"),
            priority=data.get("priority", "medium"),
            subject_id=data.get("subject_id"),
            description=data.get("description"),
        )
        db.add(task)
        db.commit()
        return f" Создана задача «{task.title}»"

    elif t == "update_task":
        task = db.query(Task).filter(Task.id == action.get("task_id"), Task.user_id == user.id).first()
        if not task:
            return " Задача не найдена"

        for k, v in action.get("data", {}).items():
            if k == "deadline":
                try:
                    setattr(task, k, datetime.fromisoformat(v))
                except Exception:
                    pass
            elif hasattr(task, k):
                setattr(task, k, v)

        db.commit()
        return f" Задача «{task.title}» обновлена"

    elif t == "delete_task":
        task = db.query(Task).filter(Task.id == action.get("task_id"), Task.user_id == user.id).first()
        if not task:
            return "Задача не найдена"

        name = task.title
        db.delete(task)
        db.commit()
        return f"Задача «{name}» удалена"

    return " Действие выполнено"




class AIChatRequest(BaseModel):
    message: str

class AIChatResponse(BaseModel):
    reply: str
    action_result: Optional[str] = None

class MsgCreate(BaseModel):
    content: str

class MsgOut(BaseModel):
    id: int
    user_id: int
    username: str
    content: str
    created_at: datetime



@router.post("/ai", response_model=AIChatResponse)
def ai_chat(
    req: AIChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    uid = current_user.id
    if uid not in histories:
        histories[uid] = []

    system = system_prompt + f"\n\n--- ТЕКУЩИЕ ДАННЫЕ ПОЛЬЗОВАТЕЛЯ ---\n{build_context(uid, db)}"

    histories[uid].append({"role": "user", "content": req.message})
    messages = [{"role": "system", "content": system}] + histories[uid][-20:]

    try:
        resp = llm().chat.completions.create(
            model=settings.AI_MODEL,
            messages=messages,
            max_tokens=1024,
            temperature=0.7,
        )
        raw = resp.choices[0].message.content or ""
    except Exception as e:
        histories[uid].pop()
        raise HTTPException(503, f"Ошибка AI: {str(e)}")

    reply, action = get_action(raw)

    action_result = None
    if action:
        action_result = do_action(action, current_user, db)

    histories[uid].append({"role": "assistant", "content": reply})
    if len(histories[uid]) > 40:
        histories[uid] = histories[uid][-40:]

    return AIChatResponse(reply=reply, action_result=action_result)

@router.delete("/ai/history", status_code=204)
def clear_ai_history(current_user: User = Depends(get_current_user)):
    histories.pop(current_user.id, None)

@router.get("/messages", response_model=List[MsgOut])
def get_messages(
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(Message)
        .order_by(desc(Message.created_at))
        .limit(limit)
        .all()
    )
    rows.reverse()

    return [
        MsgOut(
            id=m.id,
            user_id=m.user_id,
            username=m.author.username if m.author else "?",
            content=m.content,
            created_at=m.created_at,
        )
        for m in rows
    ]

@router.post("/messages", response_model=MsgOut, status_code=201)
def send_message(
    req: MsgCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not req.content.strip():
        raise HTTPException(400, "Сообщение не может быть пустым")

    msg = Message(user_id=current_user.id, content=req.content.strip())
    db.add(msg)
    db.commit()
    db.refresh(msg)

    return MsgOut(
        id=msg.id,
        user_id=msg.user_id,
        username=current_user.username,
        content=msg.content,
        created_at=msg.created_at,
    )