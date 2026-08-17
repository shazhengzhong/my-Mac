"""SQLite database for storing waybill history."""
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "waybills.db"


def get_connection():
    """Get database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize database tables."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS waybills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            waybill_no TEXT,
            departure_station TEXT,
            arrival_station TEXT,
            date TEXT,
            shipper TEXT,
            shipper_address TEXT,
            shipper_phone TEXT,
            receiver TEXT,
            receiver_address TEXT,
            contact TEXT,
            cargo_data TEXT,
            total_freight_words TEXT,
            total_freight_digits TEXT,
            payment_method TEXT,
            remarks TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def save_waybill(data: dict) -> int:
    """Save a waybill record. Returns the new record ID."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO waybills (
            waybill_no, departure_station, arrival_station, date,
            shipper, shipper_address, shipper_phone,
            receiver, receiver_address, contact,
            cargo_data, total_freight_words, total_freight_digits,
            payment_method, remarks
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("waybill_no", ""),
        data.get("departure_station", ""),
        data.get("arrival_station", ""),
        data.get("date", ""),
        data.get("shipper", ""),
        data.get("shipper_address", ""),
        data.get("shipper_phone", ""),
        data.get("receiver", ""),
        data.get("receiver_address", ""),
        data.get("contact", ""),
        data.get("cargo_data", "[]"),
        data.get("total_freight_words", ""),
        data.get("total_freight_digits", ""),
        data.get("payment_method", ""),
        data.get("remarks", ""),
    ))
    waybill_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return waybill_id


def get_waybill(waybill_id: int) -> dict:
    """Get a waybill record by ID."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM waybills WHERE id = ?", (waybill_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_recent_waybills(limit: int = 20) -> list:
    """Get recent waybill records."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, waybill_no, shipper, receiver, date, created_at
        FROM waybills
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


# Initialize database on import
init_db()
