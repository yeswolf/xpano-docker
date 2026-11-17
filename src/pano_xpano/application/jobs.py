from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Callable

from pano_xpano.application.ports import Progress, Store
from pano_xpano.domain.models import JobRecord, JobStatus

logger = logging.getLogger(__name__)


class JobRunner:
    def __init__(self, store: Store, max_workers: int = 1, inline: bool = False) -> None:
        self._store = store
        self._inline = inline
        self._executor = None if inline else ThreadPoolExecutor(max_workers=max_workers)

    def submit(
        self,
        kind: str,
        task: Callable[[Progress], dict],
        context: dict | None = None,
    ) -> JobRecord:
        job = self._store.create_job(kind, datetime.now(), context)
        if self._inline:
            self._execute(job.id, task)
            return self._store.get_job(job.id) or job
        assert self._executor is not None
        self._executor.submit(self._execute, job.id, task)
        return job

    def _execute(self, job_id: str, task: Callable[[Progress], dict]) -> None:
        self._store.update_job(job_id, status=JobStatus.RUNNING, progress=0.01)
        last_progress = 0.01

        def progress(value: float, message: str) -> None:
            nonlocal last_progress
            if value - last_progress < 0.01 and value < 1.0:
                return
            last_progress = value
            self._store.update_job(job_id, progress=value, message=message)

        try:
            result = task(progress)
        except Exception as error:
            logger.exception("job %s failed", job_id)
            self._store.update_job(
                job_id, status=JobStatus.FAILED, message=str(error)
            )
            return
        self._store.update_job(
            job_id,
            status=JobStatus.COMPLETED,
            progress=1.0,
            message="done",
            result=result,
        )

    def shutdown(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
