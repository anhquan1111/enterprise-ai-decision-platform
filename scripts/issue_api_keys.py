"""Giai doan xac thuc & do tin cay: sinh API key that cho tung nhan vien da seed,
in ra DUNG MOT LAN.

Chi luu SHA-256 hash vao cot employees.api_key_hash (sql/06_auth.sql) - khong bao
gio luu plaintext. Day la mo phong dung cach mot he thong that cap phat credential:
hien thi mot lan luc cap, nguoi nhan tu luu lai, server khong con giu ban ro nao.

Idempotent theo tung nhan vien: chay lai se CAP KEY MOI cho nhung nhan vien chua co
hash, khong dong lai key cua nhan vien da co san (tranh vo tinh vo hieu hoa key dang
dung cua nguoi khac moi lan chay lai script).

    uv run python -m scripts.issue_api_keys
"""

import hashlib
import secrets

from src.db import fetch_all, get_connection


def _hash(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def main() -> None:
    rows = fetch_all(
        "SELECT employee_id, full_name, role, department FROM employees "
        "WHERE api_key_hash IS NULL ORDER BY employee_id"
    )
    if not rows:
        print("Moi nhan vien da co API key. Khong cap them (khong ghi de key dang dung).")
        return

    print("API key MOI - chi hien thi MOT LAN, tu luu lai ngay:\n")
    with get_connection(read_only=False) as conn, conn.cursor() as cur:
        for row in rows:
            api_key = secrets.token_urlsafe(32)
            cur.execute(
                "UPDATE employees SET api_key_hash = %(hash)s WHERE employee_id = %(id)s",
                {"hash": _hash(api_key), "id": row["employee_id"]},
            )
            print(
                f"  {row['employee_id']:10} ({row['role']:10} / {row['department']:12}) "
                f"{row['full_name']:15} -> {api_key}"
            )
        conn.commit()

    print(f"\nDa cap {len(rows)} key moi. Dung header: Authorization: Bearer <key>")


if __name__ == "__main__":
    main()
