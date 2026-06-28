# metrics

- order revenue: sum of total_amount from orders where status is delivered.

# rules

## active

- active: Only count orders with status delivered unless the user asks for other statuses.

# dimensions

- novashop.orders.order_id: order id
- novashop.orders.order_date: date the order was placed
- novashop.orders.product_id: product on the order
- novashop.orders.status: order status such as delivered or pending
- novashop.products.product_id: product id
- novashop.products.product_name: product name
- novashop.products.category: product category

# measures

- novashop.orders.quantity: units ordered, default sum
- novashop.orders.total_amount: line total in dollars, default sum

# relations

- novashop.orders.product_id = novashop.products.product_id
