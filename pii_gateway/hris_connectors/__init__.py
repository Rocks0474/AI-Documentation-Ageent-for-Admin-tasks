"""HRIS connectors for the PII gateway.

Each connector returns Zone 1 employee records from a source HR system. Stubs
return realistic fake data so the gateway is exercisable locally and in tests;
real implementations replace them in deployment.
"""

from pii_gateway.hris_connectors.base import EmployeeRecord, HRISConnector

__all__ = ["EmployeeRecord", "HRISConnector"]
