from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User, Subject
from ..schemas import UserCreate, UserOut, Token
from ..auth import hash_password, verify_password, create_access_token

router = APIRouter(prefix="/api/auth", tags=["auth"])

default_subjects = [
    ("Математика", "#E74C3C"),
    ("Русский язык", "#3498DB"),
    ("Литература", "#9B59B6"),
    ("История", "#E67E22"),
    ("Физика", "#1ABC9C"),
    ("Химия", "#2ECC71"),
    ("Биология", "#F39C12"),
    ("Английский язык", "#34495E"),
    ("Информатика", "#2980B9"),
    ("Физкультура", "#27AE60"),
]

@router.post("/register", response_model=UserOut, status_code=201)
def register(data: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(400, "Username already taken")
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(400, "Email already registered")

    user = User(username=data.username, email=data.email, hashed_password=hash_password(data.password))
    db.add(user)
    db.flush()

    for name, color in default_subjects:
        db.add(Subject(name=name, color=color, user_id=user.id))

    db.commit()
    db.refresh(user)
    return user
@router.post("/login", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form.username).first()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"sub": user.username})
    return {"access_token": token, "token_type": "bearer"}1