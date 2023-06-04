from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends

from app.api.utils import is_valid_strategy_id
from app.schemas.trade import TradePostSchema
from app.schemas.trade import TradeSchema

trading_router = APIRouter(
    prefix="/api/trading",
    tags=["trading"],
)


@trading_router.post("/nfo", status_code=201, response_model=TradeSchema)
async def post_nfo(
    payload: TradePostSchema,
    strategy_id: UUID = Depends(is_valid_strategy_id),
):
    print(payload)
