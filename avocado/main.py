from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.getenv("AVOCADO_HOST", "0.0.0.0")
    port = int(os.getenv("AVOCADO_PORT", "8080"))
    uvicorn.run("avocado.web_admin:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()

