from fastapi import FastAPI

from app.routes import router

app = FastAPI(title="AutoFill Engine")

app.include_router(router)
