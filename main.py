from __future__ import annotations

import uvicorn

from backend.config import load_app_config
from backend.main import app


def main() -> None:
    config = load_app_config()
    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
    )


if __name__ == "__main__":
    main()
