import threading
from dataclasses import dataclass, field


@dataclass
class Job:
    job_id: str
    cancelled: bool = False
    complete: bool = False
    error: str | None = None
    total_chunks: int = 0
    ready_chunks: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)
    done: threading.Event = field(default_factory=threading.Event)

    def cancel(self):
        with self.lock:
            self.cancelled = True
            self.complete = True
            self.done.set()

    def is_cancelled(self) -> bool:
        with self.lock:
            return self.cancelled

    def set_total_chunks(self, total_chunks: int):
        with self.lock:
            self.total_chunks = total_chunks
            self.ready_chunks = 0
            self.error = None
            self.complete = False

    def mark_chunk_ready(self):
        with self.lock:
            self.ready_chunks += 1

    def mark_complete(self):
        with self.lock:
            self.complete = True
            self.done.set()

    def fail(self, error: str):
        with self.lock:
            self.error = error
            self.complete = True
            self.done.set()

    def wait(self, timeout: float | None = None) -> bool:
        return self.done.wait(timeout)

    def snapshot(self) -> dict[str, int | bool | str | None]:
        with self.lock:
            return {
                "job_id": self.job_id,
                "cancelled": self.cancelled,
                "complete": self.complete,
                "error": self.error,
                "total_chunks": self.total_chunks,
                "ready_chunks": self.ready_chunks,
            }


class JobRegistry:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, job_id: str) -> Job:
        job = Job(job_id=job_id)
        with self._lock:
            previous = self._jobs.get(job_id)
            if previous is not None:
                previous.cancel()
            self._jobs[job_id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job:
            job.cancel()
            return True
        return False

    def remove(self, job_id: str):
        with self._lock:
            self._jobs.pop(job_id, None)

    def cleanup(self):
        with self._lock:
            cancelled = [jid for jid, j in self._jobs.items() if j.is_cancelled()]
            for jid in cancelled:
                del self._jobs[jid]


registry = JobRegistry()
