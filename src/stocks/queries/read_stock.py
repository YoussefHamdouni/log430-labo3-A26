"""
Product (read-only model)
SPDX - License - Identifier: LGPL - 3.0 - or -later
Auteurs : Gabriel C. Ullmann, Fabio Petrillo, 2025
"""

from db import get_sqlalchemy_session
from stocks.models.product import Product
from stocks.models.stock import Stock

def get_stock_by_id(product_id):
    """Get stock by product ID """
    session = get_sqlalchemy_session()
    result = session.query(Stock).filter_by(product_id=product_id).all()
    if len(result):
        return {
            'product_id': result[0].product_id,
            'quantity': result[0].quantity,
        }
    else:
        return {}

LOW_STOCK_THRESHOLD = 10

def get_stock_for_all_products():
    """Get stock quantity for all products"""
    session = get_sqlalchemy_session()
    try:
        results = session.query(
            Stock.product_id,
            Stock.quantity,
            Product.name,
            Product.sku,
            Product.price,
        ).join(Product, Stock.product_id == Product.id).order_by(Stock.quantity.asc()).all()
    finally:
        session.close()

    stock_data = []
    for row in results:
        quantity = int(row.quantity)
        unit_price = float(row.price)
        if quantity <= 0:
            status = 'Rupture de stock'
        elif quantity < LOW_STOCK_THRESHOLD:
            status = 'Stock faible - réapprovisionner'
        else:
            status = 'OK'
        stock_data.append({
            'ID article': row.product_id,
            'Article': row.name,
            'Numéro SKU': row.sku,
            'Prix unitaire': unit_price,
            'Unités en stock': quantity,
            'Valeur du stock': round(unit_price * quantity, 2),
            'Statut': status,
        })

    return stock_data