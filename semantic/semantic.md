# metrics

# Define business metrics in plain language. Each line: `name: definition`.
# Example:
# - delivered revenue: sum of total amount from orders where order status = delivered.


# rules

# Business rules with a lifecycle status prefix. Only `active` rules are enforced.
# Example:
# - active: Exclude product P003 from all calculations; it is blacklisted.


# dimensions

# Queryable fields, one per line: `source_id.table.column: description`.
# Example:
# - my_postgres.orders.order_id: unique identifier for each order


# measures

# Numeric fields that can be aggregated: `source_id.table.column: description, default <agg>`.
# Example:
# - my_postgres.orders.total_amount: order total, default sum


# relations

# Cross-source joins: `left_field = right_field`.
# Example:
# - my_postgres.orders.customer_id = my_postgres.customers.customer_id
