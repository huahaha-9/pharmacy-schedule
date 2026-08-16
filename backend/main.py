from fastapi import FastAPI

from backend.models import ScheduleRequest
from backend.scheduler import solve_schedule


app = FastAPI(
    title="藥局自動排班 API",
    version="1.0.0",
)


@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "藥局排班 API 正常運作",
    }


@app.post("/api/schedule")
def generate_schedule(request: ScheduleRequest):
    return solve_schedule(request)
