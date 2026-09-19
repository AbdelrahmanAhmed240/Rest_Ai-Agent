from app.models.base import db
from app.models.product import Product
from app.models.customer import Customer
from app.models.order import Order, OrderItem
from app.models.knowledge import KnowledgeItem

__all__ = [
    "db",
    "Product",
    "Customer",
    "Order",
    "OrderItem",
    "KnowledgeItem",
]
