#!/usr/bin/env python3
"""Build the zero-infrastructure NovaShop DuckDB sample database.

NovaShop is a small single-store retail dataset (products, customers, orders)
used by the bundled zero-infra example. Running this script writes:

  - data/products.csv, data/customers.csv, data/orders.csv  (human-readable)
  - novashop.duckdb                                          (the queryable DB)

Generation is fully deterministic (fixed RNG seed) so the documented worked
example returns stable numbers on every machine. No external services needed.

Usage:
    pip install duckdb
    python examples/novashop-duckdb/seed.py
"""
from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
DB_PATH = HERE / "novashop.duckdb"

RNG = random.Random(42)  # deterministic: stable data => stable documented answers

# --- Catalog -------------------------------------------------------------------
# (product_id, name, category, brand, list_price, listing_status)
PRODUCTS = [
    ("NS-001", "Aurora Wireless Earbuds",     "Electronics",    "Aurora",   129.00, "active"),
    ("NS-002", "Aurora Noise-Cancel Headset", "Electronics",    "Aurora",   249.00, "active"),
    ("NS-003", "Volt 65W USB-C Charger",       "Electronics",    "Volt",      39.00, "active"),
    ("NS-004", "Volt Power Bank 20000mAh",     "Electronics",    "Volt",      59.00, "active"),
    ("NS-005", "Hearth Ceramic Cookware Set",  "Home & Kitchen", "Hearth",   189.00, "active"),
    ("NS-006", "Hearth Pour-Over Coffee Kit",  "Home & Kitchen", "Hearth",    44.00, "active"),
    ("NS-007", "Hearth Cast-Iron Skillet",     "Home & Kitchen", "Hearth",    69.00, "active"),
    ("NS-008", "Lumen Daily Vitamin C Serum",  "Beauty",         "Lumen",     32.00, "active"),
    ("NS-009", "Lumen Hydrating Day Cream",     "Beauty",         "Lumen",     28.00, "active"),
    ("NS-010", "Stride Trail Running Shoes",    "Sports",         "Stride",   140.00, "active"),
    ("NS-011", "Stride Compression Socks 3pk",  "Sports",         "Stride",    24.00, "active"),
    ("NS-012", "Stride Insulated Bottle 1L",    "Sports",         "Stride",    34.00, "active"),
    ("NS-013", "Generic Clip-On Phone Lens",    "Electronics",    "NoName",    12.00, "draft"),  # blacklisted
]

CATEGORY_DEMAND = {          # relative order volume per category (Electronics leads)
    "Electronics": 0.42,
    "Home & Kitchen": 0.24,
    "Beauty": 0.18,
    "Sports": 0.16,
}
SEGMENTS = ["consumer", "consumer", "consumer", "smb", "vip"]
REGIONS = ["West", "East", "Midwest", "South"]
CHANNELS = ["Web", "Web", "Web", "Mobile", "Marketplace"]
# Most orders are delivered; the rest exercise the delivered-only revenue rule.
STATUSES = ["delivered"] * 7 + ["returned", "cancelled", "pending"]

FIRST_NAMES = ["Ava", "Liam", "Maya", "Noah", "Zoe", "Ethan", "Iris", "Owen",
               "Nina", "Leo", "Priya", "Diego", "Sara", "Kai", "Mara", "Jonah"]
LAST_NAMES = ["Patel", "Nguyen", "Garcia", "Kim", "Okafor", "Rossi", "Haddad",
              "Silva", "Cohen", "Mori", "Singh", "Dubois", "Costa", "Reyes"]


def _build_customers(n: int) -> list[tuple]:
    customers = []
    used = set()
    for i in range(1, n + 1):
        while True:
            name = f"{RNG.choice(FIRST_NAMES)} {RNG.choice(LAST_NAMES)}"
            if name not in used:
                used.add(name)
                break
        handle = name.lower().replace(" ", ".")
        cid = f"C{i:04d}"
        email = f"{handle}@example.com"          # sensitive field (ACL-masked)
        segment = RNG.choice(SEGMENTS)
        region = RNG.choice(REGIONS)
        signup = date(2024, 1, 1) + timedelta(days=RNG.randint(0, 540))
        customers.append((cid, name, email, segment, region, signup.isoformat()))
    return customers


def _weighted_product() -> tuple:
    sellable = [p for p in PRODUCTS if p[5] == "active"]
    weights = [CATEGORY_DEMAND[p[2]] for p in sellable]
    return RNG.choices(sellable, weights=weights, k=1)[0]


def _build_orders(customers: list[tuple], n: int) -> list[tuple]:
    orders = []
    start = date(2025, 7, 1)
    span_days = (date(2026, 6, 15) - start).days
    for i in range(1, n + 1):
        product = _weighted_product()
        pid, _, _, _, list_price, _ = product
        customer = RNG.choice(customers)
        cid = customer[0]
        order_date = start + timedelta(days=RNG.randint(0, span_days))
        quantity = RNG.choices([1, 1, 1, 2, 2, 3], k=1)[0]
        # Sell at or slightly below list price.
        unit_price = round(list_price * RNG.choice([1.0, 1.0, 0.95, 0.9]), 2)
        gross = round(unit_price * quantity, 2)
        # ~35% of orders carry a discount.
        discount = round(gross * RNG.choice([0, 0, 0, 0.05, 0.1, 0.15]), 2)
        status = RNG.choice(STATUSES)
        channel = RNG.choice(CHANNELS)
        region = RNG.choice(REGIONS)
        orders.append((
            f"O{i:05d}", order_date.isoformat(), cid, pid, quantity,
            f"{unit_price:.2f}", f"{discount:.2f}", f"{gross:.2f}",
            status, channel, region,
        ))
    return orders


def _write_csv(path: Path, header: list[str], rows: list[tuple]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    customers = _build_customers(60)
    orders = _build_orders(customers, 600)

    _write_csv(DATA_DIR / "products.csv",
               ["product_id", "product_name", "category", "brand", "list_price", "listing_status"],
               [p for p in PRODUCTS])
    _write_csv(DATA_DIR / "customers.csv",
               ["customer_id", "customer_name", "email", "segment", "region", "signup_date"],
               customers)
    _write_csv(DATA_DIR / "orders.csv",
               ["order_id", "order_date", "customer_id", "product_id", "quantity",
                "unit_price", "discount_amount", "total_amount", "order_status",
                "channel", "shipping_region"],
               orders)

    import duckdb  # imported here so the CSVs are written even if the driver is missing

    if DB_PATH.exists():
        DB_PATH.unlink()
    con = duckdb.connect(str(DB_PATH))
    con.execute("""
        CREATE TABLE products (
            product_id     VARCHAR PRIMARY KEY,
            product_name   VARCHAR,
            category       VARCHAR,
            brand          VARCHAR,
            list_price     DECIMAL(10,2),
            listing_status VARCHAR
        )""")
    con.execute("""
        CREATE TABLE customers (
            customer_id   VARCHAR PRIMARY KEY,
            customer_name VARCHAR,
            email         VARCHAR,
            segment       VARCHAR,
            region        VARCHAR,
            signup_date   DATE
        )""")
    con.execute("""
        CREATE TABLE orders (
            order_id        VARCHAR PRIMARY KEY,
            order_date      DATE,
            customer_id     VARCHAR,
            product_id      VARCHAR,
            quantity        INTEGER,
            unit_price      DECIMAL(10,2),
            discount_amount DECIMAL(10,2),
            total_amount    DECIMAL(10,2),
            order_status    VARCHAR,
            channel         VARCHAR,
            shipping_region VARCHAR
        )""")
    for table in ("products", "customers", "orders"):
        con.execute(
            f"INSERT INTO {table} SELECT * FROM read_csv_auto('{(DATA_DIR / (table + '.csv')).as_posix()}', header=true)"
        )
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("products", "customers", "orders")}
    con.close()

    print(f"Built {DB_PATH.relative_to(HERE.parent.parent)}")
    print("Rows:", ", ".join(f"{t}={n}" for t, n in counts.items()))
    print("CSV mirrors written to", DATA_DIR.relative_to(HERE.parent.parent))


if __name__ == "__main__":
    main()
