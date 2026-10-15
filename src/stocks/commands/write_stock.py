"""
Product stocks (write-only model)
SPDX - License - Identifier: LGPL - 3.0 - or -later
Auteurs : Gabriel C. Ullmann, Fabio Petrillo, 2025
"""
from sqlalchemy import text
from stocks.models.stock import Stock
from stocks.models.product import Product
from db import get_redis_conn, get_sqlalchemy_session

def _get_products_info(product_ids):
    """ Read name, sku and price of the given products from MySQL (one query) """
    if not product_ids:
        return {}
    session = get_sqlalchemy_session()
    try:
        products = session.query(Product).filter(Product.id.in_(list(product_ids))).all()
        return {
            p.id: {"name": p.name, "sku": p.sku, "price": float(p.price)}
            for p in products
        }
    finally:
        session.close()

def set_stock_for_product(product_id, quantity):
    """Set stock quantity for product in MySQL"""
    session = get_sqlalchemy_session()
    try: 
        result = session.execute(
            text(f"""
                UPDATE stocks 
                SET quantity = :qty 
                WHERE product_id = :pid
            """),
            {"pid": product_id, "qty": quantity}
        )
        response_message = f"rows updated: {result.rowcount}"
        if result.rowcount == 0:
            new_stock = Stock(product_id=product_id, quantity=quantity)
            session.add(new_stock)
            response_message = f"rows added, product {new_stock.product_id}"
            session.flush() 
            session.commit()
  
        session.commit()
        r = get_redis_conn()
        product_info = _get_products_info([int(product_id)]).get(int(product_id), {})
        r.hset(f"stock:{product_id}", mapping={"quantity": quantity, **product_info})
        return response_message
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()
    
def update_stock_mysql(session, order_items, operation):
    """ Update stock quantities in MySQL according to a given operation (+/-) """
    try:
        for item in order_items:
            if hasattr(order_items[0], 'product_id'):
                pid = item.product_id
                qty = item.quantity
            else:
                pid = item['product_id']
                qty = item['quantity']
            session.execute(
                text(f"""
                    UPDATE stocks 
                    SET quantity = quantity {operation} :qty 
                    WHERE product_id = :pid
                """),
                {"pid": pid, "qty": qty}
            )
    except Exception as e:
        raise e
    
def check_out_items_from_stock(session, order_items):
    """ Decrease stock quantities in Redis """
    update_stock_mysql(session, order_items, "-")
    
def check_in_items_to_stock(session, order_items):
    """ Increase stock quantities in Redis """
    update_stock_mysql(session, order_items, "+")

def update_stock_redis(order_items, operation):
    """ Update stock quantities in Redis, with the product's name, sku and price """
    if not order_items:
        return
    r = get_redis_conn()
    stock_keys = list(r.scan_iter("stock:*"))
    if stock_keys:
        # Normaliser les articles (objets OrderItem ou dictionnaires)
        items = []
        for item in order_items:
            if hasattr(item, 'product_id'):
                items.append((int(item.product_id), int(item.quantity)))
            else:
                items.append((int(item['product_id']), int(item['quantity'])))

        # Une seule requête MySQL pour obtenir name, sku et price de tous les articles
        products_info = _get_products_info({pid for pid, _ in items})

        pipeline = r.pipeline()
        for product_id, quantity in items:
            current_stock = r.hget(f"stock:{product_id}", "quantity")
            current_stock = int(current_stock) if current_stock else 0
            new_quantity = current_stock + quantity if operation == '+' else current_stock - quantity

            stock_data = {"quantity": new_quantity}
            stock_data.update(products_info.get(product_id, {}))  # name, sku, price
            pipeline.hset(f"stock:{product_id}", mapping=stock_data)
        pipeline.execute()
    else:
        _populate_redis_from_mysql(r)

def _populate_redis_from_mysql(redis_conn):
    """ Helper function to populate Redis from MySQL stocks table """
    session = get_sqlalchemy_session()
    try:
        stocks = session.execute(
            text("""
                SELECT s.product_id, s.quantity, p.name, p.sku, p.price
                FROM stocks s JOIN products p ON s.product_id = p.id
            """)
        ).fetchall()

        if not len(stocks):
            print("Il n'est pas nécessaire de synchronisér le stock MySQL avec Redis")
            return
        
        pipeline = redis_conn.pipeline()
        
        for product_id, quantity, name, sku, price in stocks:
            pipeline.hset(
                f"stock:{product_id}",
                mapping={"quantity": quantity, "name": name, "sku": sku, "price": float(price)}
            )
        
        pipeline.execute()
        print(f"{len(stocks)} enregistrements de stock ont été synchronisés avec Redis")
        
    except Exception as e:
        print(f"Erreur de synchronisation: {e}")
        raise e
    finally:
        session.close()
