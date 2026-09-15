"""D4: metric Prometheus cho /ask. prometheus-client da la dependency tu D0
(pyproject.toml), chua tung duoc dung toi bay gio.

Dat ten theo dung quy uoc Prometheus: don vi trong ten (`_seconds`, `_total`), counter
ket thuc bang `_total`. Khong dung label co gia tri khong gioi han (vd raw question
text) - se lam no metric (cardinality explosion), chi dung label co tap gia tri co
dinh (tool_used, status, role).
"""

from prometheus_client import Counter, Histogram

ask_requests_total = Counter(
    "ask_requests_total",
    "So request /ask, theo tool_used va status code",
    labelnames=["tool_used", "status"],
)

ask_request_duration_seconds = Histogram(
    "ask_request_duration_seconds",
    "Do tre xu ly /ask tinh bang giay",
    labelnames=["tool_used"],
)

ask_auth_failures_total = Counter(
    "ask_auth_failures_total",
    "So lan xac thuc that bai o /ask (thieu header, key sai, role khong khop)",
    labelnames=["reason"],
)
