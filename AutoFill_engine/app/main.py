import logging

from fastapi import FastAPI

from app.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

app = FastAPI(title="AutoFill Engine")

app.include_router(router)
