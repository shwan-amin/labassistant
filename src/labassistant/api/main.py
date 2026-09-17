"""Entry point: `uv run labassistant-api` (or uvicorn labassistant.api.main:app)."""

import uvicorn

from labassistant.api.app import create_app
from labassistant.config import get_settings

app = create_app()


def run() -> None:
    # Always bind to the loopback interface: the API must not be reachable from
    # other machines, because it runs student code and sends it to an LLM.
    uvicorn.run("labassistant.api.main:app", host="127.0.0.1", port=get_settings().api_port)


if __name__ == "__main__":
    run()
