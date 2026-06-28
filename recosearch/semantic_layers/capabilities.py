"""What a data source can do — not what business role it plays."""

STRUCTURED_QUERY = "structured_query"
DOCUMENT_SEARCH = "document_search"
ENTITY_READ = "entity_read"
ORIGIN_ONLY = "origin_only"

ALL = frozenset({STRUCTURED_QUERY, DOCUMENT_SEARCH, ENTITY_READ, ORIGIN_ONLY})
