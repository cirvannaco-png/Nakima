"""Prometheus metrics and bounded redacted process-local logs."""
import logging,re,threading
from collections import deque
from datetime import UTC,datetime
from prometheus_client import CollectorRegistry,Counter,Histogram
REGISTRY=CollectorRegistry(auto_describe=True)
tasks_total=Counter('nakima_tasks_total','Orchestration tasks',['status'],registry=REGISTRY)
task_duration_seconds=Histogram('nakima_task_duration_seconds','Task duration seconds',registry=REGISTRY)
provider_call_duration_seconds=Histogram('nakima_provider_call_duration_seconds','Provider call seconds',['provider','action'],registry=REGISTRY)
security_findings_total=Counter('nakima_security_findings_total','Security findings',['source','severity'],registry=REGISTRY)
_LOGS=deque(maxlen=500); _LOCK=threading.Lock()
_PATTERNS=((re.compile(r'(?i)(authorization\\s*[:=]\\s*bearer\\s+)[^\\s,;]+'),r'\\1[REDACTED]'),(re.compile(r'(?i)(token|api[_-]?key|secret|password)(\\s*[:=]\\s*)[\"\']?[^\\s,;\"\']+'),r'\\1\\2[REDACTED]'),(re.compile(r'\\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\\b'),'[REDACTED_GITHUB_TOKEN]'))
def redact_log_message(value:str)->str:
    for p,r in _PATTERNS:value=p.sub(r,value)
    return value[:4000]
class BoundedLogBuffer(logging.Handler):
    def emit(self,record):
        try:
            item={'timestamp':datetime.fromtimestamp(record.created,UTC).isoformat(),'level':record.levelname,'logger':record.name[:120],'message':redact_log_message(record.getMessage())}
            with _LOCK:_LOGS.append(item)
        except Exception:self.handleError(record)
def install_log_buffer():
    root=logging.getLogger()
    if not any(isinstance(h,BoundedLogBuffer) for h in root.handlers):
        h=BoundedLogBuffer();h.setLevel(logging.INFO);root.addHandler(h)
def recent_logs(limit:int=100)->list[dict]:
    with _LOCK:return list(_LOGS)[-max(1,min(int(limit),200)):]
