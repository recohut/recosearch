# metrics

- delivered order revenue: sum of total amount from orders where order status = delivered. Excludes cancelled, returned, and pending orders.
- delivered net revenue: (is always done after discounts calculated) sum of total amount minus discount amount from orders where order status = delivered. Excludes cancelled, returned, pending orders, and globally excluded products.
- bad review count: count of customer reviews where rating is 1 or 2. Use this to identify products crossing review-risk thresholds.


# rules

- active: Ignore product P003 from all calculations, it is a blacklisted product.
- active: Any product with bad reviews more than 5 times will be under severe review and will be shown out of stock on website until the review is completed.
- active: Sales and revenue metrics must use delivered orders only unless the user explicitly asks for returned, cancelled, or pending order analysis.
- active: Discount analysis must use novamart_postgres.orders.discount_amount from orders. Do not infer discounts from product list price.
- active: Reviews tagged suspicious_positive, incentivized_review, or fake_review_pattern are trust-risk signals and must not be used to override policy concerns or bad-review thresholds.


# dimensions

- novamart_postgres.orders.order_id: unique identifier for each marketplace order
- novamart_postgres.orders.order_date: calendar date the order was placed
- novamart_postgres.orders.product_id: product SKU linked on the order line
- novamart_postgres.orders.customer_id: unique identifier for the buyer who placed the order
- novamart_postgres.orders.order_status: fulfillment state of the order such as delivered, returned, cancelled, or pending
- novamart_postgres.orders.channel: sales channel where the order originated such as Shopify or Amazon
- novamart_postgres.orders.shipping_region: shipping region for the order such as West, East, Midwest, or South
- novamart_postgres.products.product_id: unique identifier for each catalog SKU
- novamart_postgres.products.product_name: display name of the catalog SKU
- novamart_postgres.products.category: marketplace category assigned to the product such as Electronics or Beauty
- novamart_postgres.products.listing_status: catalog activation state such as draft or active
- novamart_postgres.products.seller_id: identifier of the seller who submitted the product listing
- novamart_postgres.products.submitted_at: calendar date the product listing was submitted for review
- novamart_postgres.products.brand: brand name declared for the product listing
- novamart_opensearch.customer_reviews.review_id: unique identifier for a customer review record
- novamart_opensearch.customer_reviews.order_id: order linked to the customer review
- novamart_opensearch.customer_reviews.product_id: product SKU referenced in the customer review
- novamart_opensearch.customer_reviews.customer_id: buyer who submitted the customer review
- novamart_opensearch.customer_reviews.review_title: short headline left by the customer in the review
- novamart_opensearch.customer_reviews.review_text: full free-text body left by the customer in the review
- novamart_opensearch.customer_reviews.tags: keyword labels summarizing review themes such as good audio or durable
- novamart_opensearch.customer_reviews.submitted_at: timestamp when the customer review was submitted
- novamart_qdrant.novamart_policy_chunks.chunk_id: unique identifier for a policy document chunk
- novamart_qdrant.novamart_policy_chunks.document_id: identifier of the source policy document
- novamart_qdrant.novamart_policy_chunks.document_title: title of the policy document such as NovaMart Product Listing Policy
- novamart_qdrant.novamart_policy_chunks.page_number: page number where the policy chunk appears in the source PDF
- novamart_qdrant.novamart_policy_chunks.section: policy section heading such as Prohibited Categories or Listing Requirements
- novamart_qdrant.novamart_policy_chunks.text: policy text extracted from the source PDF chunk
- novamart_qdrant.novamart_policy_chunks.source_uri: file path or URI of the source policy document
- novamart_qdrant.novamart_policy_chunks.effective_date: date the policy document takes effect
- novamart_snowflake.sellers.seller_id: unique identifier for each marketplace seller
- novamart_snowflake.sellers.seller_name: display name of the seller account
- novamart_snowflake.sellers.country: country where the seller account is registered
- novamart_snowflake.sellers.active_status: whether the seller account is active or inactive
- novamart_mongodb.seller_events.event_id: unique identifier for a seller activity event
- novamart_mongodb.seller_events.seller_id: identifier of the seller the event belongs to
- novamart_mongodb.seller_events.product_id: product SKU the seller event relates to, when applicable
- novamart_mongodb.seller_events.event_type: type of seller event such as listing_submitted, listing_approved, listing_rejected, listing_flagged, payout_issued, or account_warning
- novamart_mongodb.seller_events.occurred_at: timestamp when the seller event occurred

# measures

- novamart_postgres.orders.quantity: number of units ordered on an order line, default sum
- novamart_postgres.orders.unit_price: selling price per unit recorded on the order line, default average
- novamart_postgres.orders.total_amount: monetary value of the order line, default sum
- novamart_postgres.orders.discount_amount: discount value applied to the order line, default sum
- novamart_postgres.products.list_price: catalog list price declared for the product, default average
- novamart_postgres.products.inventory_units: available catalog inventory units for the product, default sum
- novamart_opensearch.customer_reviews.rating: star score from 1 to 5 on a customer review, default average

# relations

- novamart_postgres.orders.product_id = novamart_postgres.products.product_id
- novamart_postgres.products.product_id = novamart_postgres.orders.product_id
- novamart_postgres.orders.order_id = novamart_opensearch.customer_reviews.order_id
- novamart_postgres.orders.product_id = novamart_opensearch.customer_reviews.product_id
- novamart_postgres.orders.customer_id = novamart_opensearch.customer_reviews.customer_id
- novamart_postgres.products.product_id = novamart_opensearch.customer_reviews.product_id
- novamart_snowflake.sellers.seller_id = novamart_postgres.products.seller_id
- novamart_mongodb.seller_events.seller_id = novamart_snowflake.sellers.seller_id
- novamart_mongodb.seller_events.product_id = novamart_postgres.products.product_id