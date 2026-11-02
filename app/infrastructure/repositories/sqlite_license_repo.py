"""KeyFlint SQLite License Repository.

File: app/infrastructure/repositories/sqlite_license_repo.py
"""

from __future__ import annotations

import base64
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from app.domain.entities.license import Activation, License, LicenseStatus, Tier
from app.domain.exceptions import LicenseNotFoundError, SeatLimitExceededError
from app.domain.interfaces.license_repository import ILicenseRepository
from app.infrastructure.database.connection import transaction


class SqliteLicenseRepo(ILicenseRepository):
    """SQLite implementation of the License Repository port."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, license_entity: License) -> None:
        created_str = license_entity.created_at.isoformat()
        expires_str = (
            license_entity.expires_at.isoformat()
            if license_entity.expires_at
            else None
        )
        tier_str = (
            license_entity.tier.value
            if isinstance(license_entity.tier, Tier)
            else str(license_entity.tier)
        )
        status_str = (
            license_entity.status.value
            if isinstance(license_entity.status, LicenseStatus)
            else str(license_entity.status)
        )
        features_json = json.dumps(list(license_entity.features))
        metadata_json = json.dumps(license_entity.metadata or {})

        self._conn.execute(
            """
            INSERT INTO licenses (
                id, customer_id, license_key, tier, status,
                max_seats, current_activations, expires_at, created_at,
                signature, features, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                license_key = excluded.license_key,
                tier = excluded.tier,
                status = excluded.status,
                max_seats = excluded.max_seats,
                current_activations = excluded.current_activations,
                expires_at = excluded.expires_at,
                signature = excluded.signature,
                features = excluded.features,
                metadata_json = excluded.metadata_json
            """,
            (
                license_entity.id,
                license_entity.customer_id,
                license_entity.license_key,
                tier_str,
                status_str,
                license_entity.max_seats,
                license_entity.current_activations,
                expires_str,
                created_str,
                license_entity.signature,
                features_json,
                metadata_json,
            ),
        )

    def get_by_id(self, license_id: str) -> Optional[License]:
        cur = self._conn.execute("SELECT * FROM licenses WHERE id = ?", (license_id,))
        row = cur.fetchone()
        return self._row_to_entity(row) if row else None

    def get_by_key(self, license_key: str) -> Optional[License]:
        cur = self._conn.execute("SELECT * FROM licenses WHERE license_key = ?", (license_key,))
        row = cur.fetchone()
        if row is not None:
            return self._row_to_entity(row)

        # Fast O(1) fallback: decode license_id from superseded LIC- token payload
        if license_key and license_key.startswith("LIC-"):
            try:
                header_part = license_key.split(".", 1)[0]
                subparts = header_part.split("-", 2)
                if len(subparts) == 3 and subparts[2]:
                    b64_str = subparts[2]
                    pad = "=" * ((4 - len(b64_str) % 4) % 4)
                    payload_bytes = base64.urlsafe_b64decode((b64_str + pad).encode("ascii"))
                    payload_dict = json.loads(payload_bytes.decode("utf-8"))
                    if isinstance(payload_dict, dict) and payload_dict.get("license_id"):
                        by_id = self.get_by_id(str(payload_dict["license_id"]))
                        if by_id is not None:
                            prev_keys = by_id.metadata.get("previous_license_keys", [])
                            if isinstance(prev_keys, list) and license_key in prev_keys:
                                return by_id
            except Exception:
                pass

            escaped = (
                license_key.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            cur_prev = self._conn.execute(
                "SELECT * FROM licenses WHERE metadata_json LIKE ? ESCAPE '\\'",
                (f"%{escaped}%",),
            )
            for candidate_row in cur_prev.fetchall():
                entity = self._row_to_entity(candidate_row)
                prev_keys = entity.metadata.get("previous_license_keys", [])
                if isinstance(prev_keys, list) and license_key in prev_keys:
                    return entity
        return None

    def list_by_customer_id(self, customer_id: str) -> list[License]:
        cur = self._conn.execute(
            "SELECT * FROM licenses WHERE customer_id = ? ORDER BY created_at DESC",
            (customer_id,),
        )
        return [self._row_to_entity(row) for row in cur.fetchall()]

    get_by_customer_id = list_by_customer_id

    def find_by_payment_ref(self, ref: str) -> list[License]:
        """Finds licenses whose metadata.payment_refs contains the exact provider reference."""
        if not ref:
            return []
        escaped = ref.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        cur = self._conn.execute(
            "SELECT * FROM licenses WHERE metadata_json LIKE ? ESCAPE '\\' ORDER BY created_at DESC",
            (f"%{escaped}%",),
        )
        result: list[License] = []
        for row in cur.fetchall():
            entity = self._row_to_entity(row)
            refs = entity.metadata.get("payment_refs", [])
            if isinstance(refs, list) and ref in refs:
                result.append(entity)
        return result

    def update(self, license_entity: License) -> None:
        self.save(license_entity)

    def update_status(self, license_id: str, status: LicenseStatus) -> None:
        status_str = status.value if isinstance(status, LicenseStatus) else str(status)
        cur = self._conn.execute(
            "UPDATE licenses SET status = ? WHERE id = ?",
            (status_str, license_id),
        )
        if cur.rowcount == 0:
            raise LicenseNotFoundError(f"License with id '{license_id}' not found.")

    def record_revocation(self, license_id: str, reason: str) -> None:
        self._conn.execute(
            """
            INSERT INTO revoked_licenses (license_id, reason, revoked_at)
            VALUES (?, ?, ?)
            ON CONFLICT(license_id) DO UPDATE SET
                reason = excluded.reason,
                revoked_at = excluded.revoked_at
            """,
            (license_id, reason, datetime.now(timezone.utc).isoformat()),
        )

    def is_revoked(self, license_id: str) -> bool:
        if not license_id:
            return False
        cur = self._conn.execute(
            "SELECT 1 FROM revoked_licenses WHERE license_id = ?",
            (license_id,),
        )
        return cur.fetchone() is not None

    def record_activation(
        self,
        license_id: str,
        hardware_id: str,
        machine_name: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> bool:
        """Atomically checks seat limits and registers a machine activation.

        Idempotent: if (license_id, hardware_id) is already registered, returns True.
        """
        if not hardware_id or not hardware_id.strip():
            raise ValueError("hardware_id must not be empty or whitespace.")
        hw_norm = hardware_id.strip().lower()

        with transaction(self._conn):
            # Check if this machine is already activated for this license
            cur = self._conn.execute(
                "SELECT id FROM activations WHERE license_id = ? AND hardware_id = ?",
                (license_id, hw_norm),
            )
            if cur.fetchone() is not None:
                return True  # Already registered; idempotent success

            # Check capacity
            lic_cur = self._conn.execute(
                "SELECT current_activations, max_seats FROM licenses WHERE id = ?",
                (license_id,),
            )
            lic_row = lic_cur.fetchone()
            if lic_row is None:
                raise LicenseNotFoundError(f"License '{license_id}' not found.")

            current_acts = lic_row["current_activations"]
            max_seats = lic_row["max_seats"]

            if current_acts >= max_seats:
                raise SeatLimitExceededError(
                    f"Activation limit reached ({current_acts}/{max_seats}). Upgrade your license to add seats."
                )

            # Insert activation record
            act_id = str(uuid.uuid4())
            self._conn.execute(
                """
                INSERT INTO activations (id, license_id, hardware_id, machine_name, ip_address)
                VALUES (?, ?, ?, ?, ?)
                """,
                (act_id, license_id, hw_norm, machine_name, ip_address),
            )

            # Increment count in licenses table
            self._conn.execute(
                "UPDATE licenses SET current_activations = current_activations + 1 WHERE id = ?",
                (license_id,),
            )
            return True

    def get_activations(self, license_id: str) -> list[Activation]:
        cur = self._conn.execute(
            "SELECT * FROM activations WHERE license_id = ? ORDER BY activated_at DESC",
            (license_id,),
        )
        activations = []
        for r in cur.fetchall():
            act_at = (
                datetime.fromisoformat(r["activated_at"])
                if isinstance(r["activated_at"], str)
                else r["activated_at"]
            )
            if act_at.tzinfo is None:
                act_at = act_at.replace(tzinfo=timezone.utc)
            activations.append(
                Activation(
                    id=r["id"],
                    license_id=r["license_id"],
                    hardware_id=r["hardware_id"],
                    machine_name=r["machine_name"],
                    ip_address=r["ip_address"],
                    activated_at=act_at,
                )
            )
        return activations

    def get_activation(self, license_id: str, hardware_id: str) -> Optional[Activation]:
        hw_norm = hardware_id.strip().lower()
        cur = self._conn.execute(
            "SELECT * FROM activations WHERE license_id = ? AND hardware_id = ?",
            (license_id, hw_norm),
        )
        r = cur.fetchone()
        if not r:
            return None
        act_at = (
            datetime.fromisoformat(r["activated_at"])
            if isinstance(r["activated_at"], str)
            else r["activated_at"]
        )
        if act_at.tzinfo is None:
            act_at = act_at.replace(tzinfo=timezone.utc)
        return Activation(
            id=r["id"],
            license_id=r["license_id"],
            hardware_id=r["hardware_id"],
            machine_name=r["machine_name"],
            ip_address=r["ip_address"],
            activated_at=act_at,
        )

    def count_activations(self, license_id: str) -> int:
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM activations WHERE license_id = ?",
            (license_id,),
        )
        return cur.fetchone()[0]

    @staticmethod
    def _row_to_entity(row: sqlite3.Row) -> License:
        row_keys = set(row.keys())
        created_at = (
            datetime.fromisoformat(row["created_at"])
            if isinstance(row["created_at"], str)
            else row["created_at"]
        )
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        expires_at = None
        if row["expires_at"]:
            expires_at = (
                datetime.fromisoformat(row["expires_at"])
                if isinstance(row["expires_at"], str)
                else row["expires_at"]
            )
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

        tier_enum = Tier(row["tier"])
        features: tuple[str, ...] = ()
        if "features" in row_keys and row["features"]:
            try:
                parsed_feat = json.loads(row["features"])
                if isinstance(parsed_feat, list) and parsed_feat:
                    features = tuple(str(x) for x in parsed_feat)
            except Exception:
                pass

        if not features:
            try:
                raw_key = row["license_key"]
                if raw_key and "." in raw_key:
                    body_part = raw_key.split(".")[0]
                    b64_str = body_part.split("-", 2)[-1] if "-" in body_part else body_part
                    pad = "=" * ((4 - len(b64_str) % 4) % 4)
                    p_bytes = base64.urlsafe_b64decode((b64_str + pad).encode("ascii"))
                    p_dict = json.loads(p_bytes.decode("utf-8"))
                    if isinstance(p_dict, dict) and isinstance(p_dict.get("features"), list):
                        features = tuple(str(x) for x in p_dict["features"])
            except Exception:
                pass

        if not features:
            features = tier_enum.default_features

        metadata: dict[str, Any] = {}
        if "metadata_json" in row_keys and row["metadata_json"]:
            try:
                parsed_meta = json.loads(row["metadata_json"])
                if isinstance(parsed_meta, dict):
                    metadata = parsed_meta
            except Exception:
                metadata = {}

        return License(
            id=row["id"],
            customer_id=row["customer_id"],
            license_key=row["license_key"],
            tier=tier_enum,
            status=LicenseStatus(row["status"]),
            max_seats=row["max_seats"],
            current_activations=row["current_activations"],
            expires_at=expires_at,
            created_at=created_at,
            signature=row["signature"],
            features=features,
            metadata=metadata,
        )
