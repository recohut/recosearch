#!/usr/bin/env python3
"""Create examples/novashop/shop.duckdb with sample data."""

from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
DB = HERE / "shop.duckdb"


def main() -> None:
    if DB.exists():
        DB.unlink()
    con = duckdb.connect(str(DB))
    con.execute(
        """
        CREATE TABLE customers (
          customer_id VARCHAR,
          customer_name VARCHAR
        );
        CREATE TABLE products (
          product_id VARCHAR,
          product_name VARCHAR,
          category VARCHAR
        );
        CREATE TABLE orders (
          order_id VARCHAR,
          order_date DATE,
          product_id VARCHAR,
          customer_id VARCHAR,
          status VARCHAR,
          quantity INTEGER,
          total_amount DOUBLE,
          refund_amount DOUBLE
        );
        CREATE TABLE order_items (
          line_id VARCHAR,
          order_id VARCHAR,
          sku VARCHAR,
          quantity INTEGER
        );
        """
    )
    con.executemany(
        "INSERT INTO customers VALUES (?, ?)",
        [
            ("C1", "Alice"),
            ("C2", "Bob"),
        ],
    )
    con.executemany(
        "INSERT INTO products VALUES (?, ?, ?)",
        [
            ("P001", "White Shoes", "Footwear"),
            ("P002", "Blue Shirt", "Apparel"),
        ],
    )
    con.executemany(
        "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("O1", "2026-01-10", "P001", "C1", "delivered", 1, 49.99, 0.00),
            ("O2", "2026-01-11", "P002", "C1", "delivered", 2, 59.98, 5.00),
            ("O3", "2026-01-12", "P001", "C2", "pending", 1, 49.99, 0.00),
        ],
    )
    con.executemany(
        "INSERT INTO order_items VALUES (?, ?, ?, ?)",
        [
            ("L1", "O1", "SKU-O1", 1),
            ("L2a", "O2", "SKU-O2a", 1),
            ("L2b", "O2", "SKU-O2b", 1),
            ("L3", "O3", "SKU-O3", 1),
        ],
    )
    con.close()
    print(f"created {DB}")


# Build on execution. This is a build script, never imported for its API — run
# both as `python build_db.py` and via runpy.run_path (test fixtures), which sets
# __name__ to "<run_path>", not "__main__", so a __main__ guard would skip the build.
main()
