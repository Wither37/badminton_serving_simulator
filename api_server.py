#!/usr/bin/env python3
"""
FastAPI server to test the servemachine_api router
"""
import uvicorn
from fastapi import FastAPI

# Import the router from servemachine_api.py
from utils.servemachine_api import router

app = FastAPI(
    title="Badminton Machine API",
    description="API for controlling badminton training machines via MQTT",
    version="1.0.0"
)

# Include the machine router
app.include_router(router)

@app.get("/")
def root():
    return {"message": "Badminton Machine API Server", "status": "running"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    print("Starting Badminton Machine API Server...")
    print("API Documentation: http://localhost:8000/docs")
    print("Redoc Documentation: http://localhost:8000/redoc")
    uvicorn.run(app, host="0.0.0.0", port=8000)