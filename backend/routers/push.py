from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import PushSubscription, User
from ..schemas import NotifySettings, NotifySettingsUpdate, PushSubscribeRequest, PushUnsubscribeRequest
from ..auth import get_current_user
from ..config import settings
from ..push_service import send_to_user

router = APIRouter(prefix="/api/push", tags=["push"])

@router.get("/vapid-public-key")
def vapid_public_key():
    return {"publicKey": settings.VAPID_PUBLIC_KEY}
@router.get("/settings", response_model=NotifySettings)
def get_notify_settings(current_user: User = Depends(get_current_user)):
    return current_user
@router.put("/settings", response_model=NotifySettings)
def update_notify_settings(
    data: NotifySettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(current_user, k, v)

    db.commit()
    db.refresh(current_user)
    return current_user
@router.post("/subscribe", status_code=204)
def subscribe(
    data: PushSubscribeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sub = db.query(PushSubscription).filter(PushSubscription.endpoint == data.endpoint).first()
    if sub:
        sub.user_id = current_user.id
        sub.p256dh = data.keys.p256dh
        sub.auth = data.keys.auth
        db.commit()
        return

    db.add(PushSubscription(
        user_id=current_user.id,
        endpoint=data.endpoint,
        p256dh=data.keys.p256dh,
        auth=data.keys.auth,
    ))
    db.commit()
@router.post("/unsubscribe", status_code=204)
def unsubscribe(
    data: PushUnsubscribeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db.query(PushSubscription).filter(
        PushSubscription.endpoint == data.endpoint,
        PushSubscription.user_id == current_user.id,
    ).delete()
    db.commit()
@router.post("/test", status_code=204)
def send_test(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    send_to_user(db, current_user, {
        "title": "StudyBalance",
        "body": "Уведомления подключены и работают!",
        "url": "/",
    })