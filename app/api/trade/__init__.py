from fastapi import APIRouter


trading_router = APIRouter(
    prefix="/api/trading",
    tags=["trading"],
)
