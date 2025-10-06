"""Backward-compatible entrypoint for the new backend server."""
from backend_server import app  # noqa: F401
import uvicorn

if __name__ == "__main__":
    uvicorn.run("backend_server:app", host="127.0.0.1", port=8001, reload=False)
