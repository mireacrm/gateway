"""Личность вызывающего и заголовки, которыми она едет дальше.

Имя кодируется процентами: заголовок HTTP допускает только ASCII, а имя
пользователя вполне может оказаться кириллицей.
"""

from dataclasses import dataclass, replace
from urllib.parse import quote

HEADER_SUBJECT = "x-user-id"
HEADER_USERNAME = "x-user-name"
HEADER_ROLES = "x-user-roles"
HEADER_EMPLOYEE = "x-employee-id"

HEADERS = frozenset({HEADER_SUBJECT, HEADER_USERNAME, HEADER_ROLES, HEADER_EMPLOYEE})

# Роли, которым видно чужое. Специалист работает только со своим.
PRIVILEGED = frozenset({"admin", "manager"})


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    username: str
    roles: frozenset[str]
    employee_id: str = ""

    def has_any(self, required: frozenset[str]) -> bool:
        return bool(self.roles & required)

    @property
    def privileged(self) -> bool:
        return bool(self.roles & PRIVILEGED)

    def with_employee(self, employee_id: str) -> "Principal":
        return replace(self, employee_id=employee_id)

    def headers(self) -> dict[str, str]:
        return {
            HEADER_SUBJECT: self.subject,
            HEADER_USERNAME: quote(self.username),
            HEADER_ROLES: ",".join(sorted(self.roles)),
            HEADER_EMPLOYEE: self.employee_id,
        }
