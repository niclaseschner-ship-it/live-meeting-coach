"""Start: python -m coach  →  http://127.0.0.1:8000"""

import uvicorn

from .config import EINST

if __name__ == "__main__":
    uvicorn.run("coach.server:app", host="127.0.0.1", port=EINST.port)
