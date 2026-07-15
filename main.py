from fastapi import FastAPI

from app.api import tasks, webhook

app = FastAPI()

@app.get("/health")
def health_check():
    return {"status": "healthy"}


app.include_router(webhook.router)
app.include_router(tasks.router)
