import time
import asyncio


class LLMRateLimiter:
    """
    Ограничитель: пауза между запросами + лимит N запросов в минуту.
    """
    def __init__(self, pause_between: float, requests_per_minute: int, logger):
        self.pause = pause_between
        self.rpm = requests_per_minute
        self.history = []  # timestamps
        self.logger = logger

    async def wait_for_slot(self):
        now = time.time()
        window_start = now - 60

        # очищаем историю от старых запросов
        self.history = [t for t in self.history if t > window_start]

        # если превышен лимит RPM — ждем
        if len(self.history) >= self.rpm:
            sleep_time = self.history[0] + 60 - now
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

        # пауза между запросами
        if self.pause > 0:
            self.logger.debug(f"Wait query {self.pause} secs")
            await asyncio.sleep(self.pause)

        # регистрируем запрос
        self.history.append(time.time())


class LLMQueueService:
    """
    Единая очередь запросов к LLM.
    Все вызовы проходят строго по одному.
    """
    def __init__(self, pause_between_requests: float, requests_per_minute: int, logger):
        self.limiter = LLMRateLimiter(pause_between_requests, requests_per_minute, logger)
        self.queue = asyncio.Queue()
        self.worker_task = None
        self.logger = logger

    async def start(self):
        """Запуск фонового воркера."""
        if self.worker_task is None:
            self.worker_task = asyncio.create_task(self._worker())
            self.logger.info(f"Worker task created")


    async def stop(self):
        """Остановка фонового воркера."""
        if self.worker_task:
            self.logger.info(f"Worker stop")
            self.worker_task.cancel()

    async def _worker(self):
        """Воркер, последовательно выполняющий запросы."""
        while True:
            future, fn, args, kwargs = await self.queue.get()

            try:
                await self.limiter.wait_for_slot()
                result = await fn(*args, **kwargs)
                future.set_result(result)
            except Exception as e:
                future.set_exception(e)
                self.logger.error(e)
            finally:
                self.queue.task_done()

    async def call(self, fn, *args, **kwargs):
        """
        Добавить запрос в очередь.
        fn — корутина Gigachat: state.gigachat_client.achat(...)
        """
        loop = asyncio.get_event_loop()
        future = loop.create_future()

        await self.queue.put((future, fn, args, kwargs))
        self.logger.debug("Queue put")

        return await future