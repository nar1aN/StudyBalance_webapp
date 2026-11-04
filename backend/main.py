import asyncio
import logging
import os

from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse

from .database import engine, Base, SessionLocal
from .models import User
from .schemas import UserOut
from .auth import get_current_user
from .config import settings
from .push_service import check_reminders
from .routers import auth, tasks, subjects, chat, push

Base.metadata.create_all(bind=engine)

migrations = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS notify_day BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS notify_urgent BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS notify_overload BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS notify_morning BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS overload_threshold DOUBLE PRECISION NOT NULL DEFAULT 4.0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_morning_notified TIMESTAMPTZ",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_overload_notified TIMESTAMPTZ",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS notified_day_at TIMESTAMPTZ",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS notified_urgent_at TIMESTAMPTZ",
]

def run_migrations():
    with engine.begin() as conn:
        for q in migrations:
            conn.exec_driver_sql(q)

run_migrations()

app = FastAPI(title="StudyBalance API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

base_dir = os.path.dirname(__file__)
static_dir = os.path.join(base_dir, "..", "frontend", "static")
index_path = os.path.join(base_dir, "..", "frontend", "templates", "index.html")

app.mount("/static", StaticFiles(directory=static_dir), name="static")

app.include_router(tasks.router)
app.include_router(subjects.router)
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(push.router)

reminder_task = None

def get_index_html():
    with open(index_path, "r", encoding="utf-8") as f:
        return f.read()
@app.get("/api/auth/me", response_model=UserOut, tags=["auth"])
def me(current_user: User = Depends(get_current_user)):
    return current_user
@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse(content=get_index_html())
@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    return FileResponse(os.path.join(static_dir, "sw.js"), media_type="application/javascript")
async def reminder_loop():
    while True:
        try:
            db = SessionLocal()
            try:
                check_reminders(db)
            finally:
                db.close()
        except Exception:
            logging.getLogger("push").exception("Reminder check failed")

        await asyncio.sleep(settings.REMINDER_CHECK_INTERVAL_SECONDS)
@app.on_event("startup")
async def start_reminders():
    global reminder_task
    reminder_task = asyncio.create_task(reminder_loop())
@app.on_event("shutdown")
async def stop_reminders():
    if reminder_task:
        reminder_task.cancel()
@app.get("/{full_path:path}", response_class=HTMLResponse)
async def serve_frontend(full_path: str):
    return HTMLResponse(content=get_index_html())