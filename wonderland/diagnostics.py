"""Local generation audit trail. Never serialize SDK requests, headers or image data."""
from __future__ import annotations

import json
import re
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path


def redact(value):
    if isinstance(value, str):
        value = re.sub(r'sk-[A-Za-z0-9_\-]+', '[REDACTED]', value)
        value = re.sub(r'(?i)(Bearer\s+)[^\s\"\']+', r'\1[REDACTED]', value)
        value = re.sub(r'(?i)((?:OPENAI_API_KEY|api_key|authorization)\s*[=:]\s*)[^\s,;]+', r'\1[REDACTED]', value)
        return re.sub(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+', '[IMAGE OMITTED]', value)
    if isinstance(value, dict):
        return {k: '[REDACTED]' if k.lower() in ('api_key', 'authorization', 'openai_api_key') else redact(v)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


def safe_error(exc: BaseException) -> str:
    if isinstance(exc, (ValueError, RuntimeError, FileNotFoundError, TypeError, KeyError, AttributeError)):
        return redact(str(exc))
    status = getattr(exc, 'status_code', None)
    body = getattr(exc, 'body', None)
    # Keep useful API validation messages, but never dump the response/request object.
    detail = body.get('message', '') if isinstance(body, dict) else ''
    return redact(f'{type(exc).__name__}' + (f' (HTTP {status})' if status else '') + (f': {detail[:1200]}' if detail else ''))


def exception_fields(exc: BaseException):
    return dict(error=safe_error(exc), error_type=type(exc).__name__,
                http_status=getattr(exc, 'status_code', None), request_id=getattr(exc, 'request_id', None),
                stack=[dict(file=frame.filename, line=frame.lineno, function=frame.name)
                       for frame in traceback.extract_tb(exc.__traceback__)])


def atomic_json(path: Path, value):
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        tmp.write_text(json.dumps(redact(value), ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


class EventLog:
    def __init__(self, root: Path, job_id: str):
        self.path = root / 'logs' / f'{job_id}.jsonl'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.job_id = job_id
        self.run_id = uuid.uuid4().hex[:12]

    def emit(self, event: str, **fields):
        row = {'timestamp':datetime.now(timezone.utc).isoformat(), 'time':time.time(),
               **fields, 'job_id':self.job_id, 'run_id':self.run_id, 'event':event}
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(redact(row), ensure_ascii=False) + '\n')


class JobLock:
    """macOS advisory lock released by the OS even after a crash."""
    def __init__(self, path):
        self.path = path
        self.stream = None

    def __enter__(self):
        import fcntl
        self.stream = self.path.open('a')
        try:
            fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.stream.close()
            raise RuntimeError('同一描述和种子的生成任务正在运行，请等待完成或先取消。') from None
        return self

    def __exit__(self, *args):
        self.stream.close()
