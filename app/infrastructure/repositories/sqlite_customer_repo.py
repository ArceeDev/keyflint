"""KeyFlint SQLite Customer Repository.

File: app/infrastructure/repositories/sqlite_customer_repo.py
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional

from app.domain.entities.customer import Customer
from app.domain.interfaces.customer_repository import ICustomerRepository


class SqliteCustomerRepo(ICustomerRepository):
    """SQLite implementation of the Customer Repository port."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, customer: Customer) -> None:
        created_str = customer.created_at.isoformat()
        updated_str = customer.updated_at.isoformat()
        self._conn.execute(
            """
            INSERT INTO customers (id, email, company, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                email = excluded.email,
                company = excluded.company,
                updated_at = excluded.updated_at
            """,
            (customer.id, customer.email, customer.company, created_str, updated_str),
        )

    def get_by_id(self, customer_id: str) -> Optional[Customer]:
        cur = self._conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,))
        row = cur.fetchone()
        return self._row_to_entity(row) if row else None

    def get_by_email(self, email: str) -> Optional[Customer]:
        cleaned = email.strip()
        cur = self._conn.execute(
            "SELECT * FROM customers WHERE email = ? OR LOWER(email) = LOWER(?)",
            (cleaned, cleaned),
        )
        row = cur.fetchone()
        return self._row_to_entity(row) if row else None

    def update(self, customer: Customer) -> None:
        self.save(customer)

    def delete(self, customer_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
        return cur.rowcount > 0

    def list_customers(self, limit: int = 100, offset: int = 0) -> list[Customer]:
        cur = self._conn.execute(
            "SELECT * FROM customers ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [self._row_to_entity(row) for row in cur.fetchall()]

    @staticmethod
    def _row_to_entity(row: sqlite3.Row) -> Customer:
        created_at = (
            datetime.fromisoformat(row["created_at"])
            if isinstance(row["created_at"], str)
            else row["created_at"]
        )
        updated_at = (
            datetime.fromisoformat(row["updated_at"])
            if isinstance(row["updated_at"], str)
            else row["updated_at"]
        )
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)

        return Customer(
            id=row["id"],
            email=row["email"],
            company=row["company"],
            created_at=created_at,
            updated_at=updated_at,
        )
