from fastapi import APIRouter, Depends, HTTPException, status, Response, Cookie
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserResponse, TokenResponse
from app.core.security import get_password_hash, verify_password, create_access_token, create_refresh_token, decode_token
from app.core.config import settings
from app.core import rate_limit
from app.api.deps import get_current_user
import jwt

router = APIRouter()

# Auth rate-limit budgets. Numeric values live in config so production can tune
# them without a code change; the scopes keep the counters in separate buckets.
_REGISTER_IP = rate_limit.Limit(
    "register-ip", settings.REGISTER_IP_LIMIT, settings.REGISTER_IP_WINDOW_SECONDS
)
_LOGIN_IP = rate_limit.Limit(
    "login-ip", settings.LOGIN_IP_LIMIT, settings.LOGIN_IP_WINDOW_SECONDS
)
_LOGIN_ACCOUNT = rate_limit.Limit(
    "login-account",
    settings.LOGIN_ACCOUNT_LIMIT,
    settings.LOGIN_ACCOUNT_WINDOW_SECONDS,
)
_REFRESH_IP = rate_limit.Limit(
    "refresh-ip", settings.REFRESH_IP_LIMIT, settings.REFRESH_IP_WINDOW_SECONDS
)

# Instantiated once so every route shares the same in-process store.
_register_ip_guard = rate_limit.limit_by_ip(_REGISTER_IP)
_login_ip_guard = rate_limit.limit_by_ip(_LOGIN_IP)
_login_account_guard = rate_limit.limit_by_account(_LOGIN_ACCOUNT)
_refresh_ip_guard = rate_limit.limit_by_ip(_REFRESH_IP)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(
    user_in: UserCreate,
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(_register_ip_guard),
):
    """Register a new user."""
    user = db.query(User).filter(User.email == user_in.email).first()
    if user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = get_password_hash(user_in.password)
    db_user = User(email=user_in.email, hashed_password=hashed_password)
    
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

@router.post("/login", response_model=TokenResponse)
def login(
    response: Response, 
    form_data: OAuth2PasswordRequestForm = Depends(), 
    db: Session = Depends(get_db),
    _rate_limit_ip: None = Depends(_login_ip_guard),
    _rate_limit_account: None = Depends(_login_account_guard),
):
    """Authenticate user, return access token, and set HttpOnly refresh cookie."""
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    
    access_token = create_access_token(subject=user.id)
    refresh_token = create_refresh_token(subject=user.id)
    
    # Set HttpOnly cookie for the refresh token
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.ENVIRONMENT == "production",
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    )
    
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/refresh", response_model=TokenResponse)
def refresh_token(
    refresh_token: str = Cookie(None),
    _rate_limit: None = Depends(_refresh_ip_guard),
):
    """Generate a new access token using the HttpOnly refresh token cookie."""
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token missing")
        
    try:
        payload = decode_token(refresh_token)
        user_id = payload.get("sub")
        token_type = payload.get("type")
        
        if user_id is None or token_type != "refresh":
            raise HTTPException(status_code=401, detail="Invalid refresh token")
            
        new_access_token = create_access_token(subject=user_id)
        return {"access_token": new_access_token, "token_type": "bearer"}
        
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

@router.post("/logout")
def logout(response: Response):
    """Clear the refresh token cookie."""
    response.delete_cookie(key="refresh_token", httponly=True, secure=settings.ENVIRONMENT == "production", samesite="lax")
    return {"message": "Successfully logged out"}

@router.get("/me", response_model=UserResponse)
def get_current_user_profile(current_user: User = Depends(get_current_user)):
    """Fetch the currently logged in user's profile."""
    return current_user