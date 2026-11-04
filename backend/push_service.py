import json
import logging
from datetime import datetime, timedelta, timezone

from pywebpush import webpush, WebPushException

from .config import settings
from .models import PushSubscription, Task, User

logger = logging.getLogger("push")

def send_to_sub(db, sub, payload):
    try:
        webpush(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=settings.VAPID_PRIVATE_KEY_PATH,
            vapid_claims={"sub": settings.VAPID_CLAIM_EMAIL},
        )
        return True
    except WebPushException as e:
        code = e.response.status_code if e.response is not None else None
        if code in (404, 410):
            db.delete(sub)
            db.commit()
        else:
            logger.warning("Push failed for subscription %s: %s", sub.id, e)
        return False
def send_to_user(db, user, payload):
    sent = 0
    for sub in list(user.push_subscriptions):
        if send_to_sub(db, sub, payload):
            sent += 1
    return sent
def check_reminders(db):
    now = datetime.now(timezone.utc)
    today = now.date()

    users = (
        db.query(User)
        .join(PushSubscription, PushSubscription.user_id == User.id)
        .distinct()
        .all()
    )

    for user in users:
        tasks = (
            db.query(Task)
            .filter(Task.user_id == user.id, Task.is_completed == False, Task.deadline.isnot(None))
            .all()
        )

        if user.notify_urgent:
            for t in tasks:
                if t.notified_urgent_at is not None:
                    continue
                left = t.deadline - now
                if timedelta(0) < left <= timedelta(hours=2):
                    send_to_user(db, user, {
                        "title": "Срочный дедлайн",
                        "body": f"«{t.title}» нужно сдать менее чем через 2 часа",
                        "url": "/",
                    })
                    t.notified_urgent_at = now
                    db.commit()

        if user.notify_day:
            for t in tasks:
                if t.notified_day_at is not None:
                    continue
                left = t.deadline - now
                if timedelta(0) < left <= timedelta(hours=24):
                    send_to_user(db, user, {
                        "title": "Дедлайн завтра",
                        "body": f"«{t.title}» нужно сдать в течение суток",
                        "url": "/",
                    })
                    t.notified_day_at = now
                    db.commit()

        if user.notify_overload:
            was = user.last_overload_notified and user.last_overload_notified.date() == today
            if not was:
                hours = sum(t.estimated_hours or 0 for t in tasks if t.deadline.date() == today)
                if hours > user.overload_threshold:
                    send_to_user(db, user, {
                        "title": "Перегруз сегодня",
                        "body": f"На сегодня запланировано {hours:.1f}ч задач — это больше нормы ({user.overload_threshold}ч)",
                        "url": "/",
                    })
                    user.last_overload_notified = now
                    db.commit()

        if user.notify_morning and 7 <= now.hour < 10:
            was = user.last_morning_notified and user.last_morning_notified.date() == today
            if not was:
                today_tasks = [t for t in tasks if t.deadline.date() == today]
                if today_tasks:
                    hours = sum(t.estimated_hours or 0 for t in today_tasks)
                    send_to_user(db, user, {
                        "title": "Доброе утро",
                        "body": f"Сегодня {len(today_tasks)} задач(и) на {hours:.1f}ч",
                        "url": "/",
                    })
                user.last_morning_notified = now
                db.commit()