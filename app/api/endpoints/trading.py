from fastapi import APIRouter

healthcheck_router = APIRouter(
    tags=["healthcheck"],
)


@healthcheck_router.get("/")
async def healthcheck():
    return {"status": "ok"}
