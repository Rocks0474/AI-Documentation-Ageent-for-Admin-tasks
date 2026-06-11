"""PII gateway package.

The PII gateway is the only component permitted to touch real employee personal
data. :class:`~pii_gateway.detector.PIIDetector` is the pre-flight guard that
agents use to refuse any payload containing Zone 1 data before it can reach the
LLM layer.
"""
