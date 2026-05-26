from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def api_health():
    return {"status": "ok"}


@router.get("/")
def api_health_slash():
    return {"status": "ok"}