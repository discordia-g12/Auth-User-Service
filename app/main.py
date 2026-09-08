from fastapi import FastAPI

app = FastAPI(title="Auth User Service")

@app.get("/")
def read_root():
    return {"message": "Welcome to Auth User Service API"}
