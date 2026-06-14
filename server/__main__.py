"""Entry point for `python -m server`.

Boots the FastAPI/uvicorn server, which in turn starts the MAVLink
bridge thread via the app's lifespan handler (see `server/app.py`).
"""

from __future__ import annotations

import logging

import uvicorn

from server.config import get_settings


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = get_settings()
    uvicorn.run("server.app:app", host=settings.server_host, port=settings.server_port)


if __name__ == "__main__":
    main()
