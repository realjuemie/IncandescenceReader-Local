from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from typing import Any, Coroutine


class AsyncRuntime:
    """让 twscrape 的异步数据库与锁始终运行在同一个事件循环。"""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._serve, name="scraper-runtime", daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coroutine: Coroutine[Any, Any, Any]) -> Future[Any]:
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def run(self, coroutine: Coroutine[Any, Any, Any], timeout: float | None = None) -> Any:
        return self.submit(coroutine).result(timeout=timeout)

    async def await_result(self, coroutine: Coroutine[Any, Any, Any]) -> Any:
        return await asyncio.wrap_future(self.submit(coroutine))

    def stop(self) -> None:
        if not self.loop.is_running():
            return
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)
        self.loop.close()
