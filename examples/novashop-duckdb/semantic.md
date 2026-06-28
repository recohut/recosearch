# metrics

- delivered order revenue: sum of total amount from orders where order status = delivered. Excludes returned, cancelled, and pending orders.
- delivered net revenue: (is always done after discounts calculated) sum of total amount minus discount amount from orders where order status = delivered. Excludes returned, cancelled, pending orders, and globally excluded products.
- units sold: sum of quantity from orders where order status = delivered.


# rules

- active: Ignore product NS-013 from all calculations, it is a blacklisted product.
- active: Sales and revenue metrics must use delivered orders only unless the user explicitly asks for returned, cancelled, or pending order analysis.
- active: Discount analysis must use novashop.orders.discount_amount from orders. Do not infer discounts from product list price.


# dimensions

- novashop.orders.order_id: unique identifier for each store order
- novashop.orders.order_date: calendar date the order was placed
- novashop.orders.customer_id: unique identifier for the buyer who placed the order
- novashop.orders.product_id: product SKU linked on the order line
- novashop.orders.order_status: fulfillment state of the order such as delivered, returned, cancelled, or pending
- novashop.orders.channel: sales channel where the order originated such as Web, Mobile, or Marketplace
- novashop.orders.shipping_region: shipping region for the order such as West, East, Midwest, or South
- novashop.products.product_id: unique identifier for each catalog SKU
- novashop.products.product_name: display name of the catalog SKU
- novashop.products.category: catalog category assigned to the product such as Electronics or Beauty
- novashop.products.brand: brand name declared for the product listing
- novashop.products.listing_status: catalog activation state such as draft or active
- novashop.customers.customer_id: unique identifier for the buyer
- novashop.customers.customer_name: display name of the customer
- novashop.customers.email: contact email address for the customer
- novashop.customers.segment: customer segment such as consumer, smb, or vip
- novashop.customers.region: home region declared for the customer


# measures

- novashop.orders.quantity: number of units ordered on an order line, default sum
- novashop.orders.unit_price: selling price per unit recorded on the order line, default average
- novashop.orders.total_amount: monetary value of the order line, default sum
- novashop.orders.discount_amount: discount value applied to the order line, default sum
- novashop.products.list_price: catalog list price declared for the product, default average


# relations

- novashop.orders.product_id = novashop.products.product_id
- novashop.products.product_id = novashop.orders.product_id
- novashop.orders.customer_id = novashop.customers.customer_id
- novashop.customers.customer_id = novashop.orders.customer_id
