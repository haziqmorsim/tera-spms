from fastapi import APIRouter
from app.api.routes import plants, inverters, alarms, kpis

api_router = APIRouter()

api_router.include_router(plants.router, prefix="/plants", tags=["plants"])
api_router.include_router(inverters.router, prefix="/inverters", tags=["inverters"])
api_router.include_router(alarms.router, prefix="/alarms", tags=["alarms"])
api_router.include_router(kpis.router, prefix="/kpis", tags=["kpis"])