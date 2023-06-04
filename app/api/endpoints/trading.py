from fastapi import APIRouter

from app.schemas.trade import TradePostSchema
from app.schemas.trade import TradeSchema

trading_router = APIRouter(
    prefix="/api/trading",
    tags=["trading"],
)


@trading_router.post("/nfo", status_code=201, response_model=TradeSchema)
def post_nfo(
    payload: TradePostSchema,
):
    print(payload)
