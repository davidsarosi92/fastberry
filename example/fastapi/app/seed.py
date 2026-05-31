"""Seed the database with a deep tree.

python -m app.seed                 # defaults: 200 x 4 x 8
python -m app.seed 500 4 8         # houses spaces stocks
"""

import random
import sys
from decimal import Decimal

from app.db import SessionLocal, engine
from app.models import Base, House, Product, Space, Stock


def seed(houses: int = 200, spaces: int = 4, stocks: int = 8, products: int = 50) -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    rng = random.Random(42)

    with SessionLocal() as s:
        product_pool = [
            Product(name=f"Product {i}", ean=f"{4000000000000 + i}") for i in range(1, products + 1)
        ]
        s.add_all(product_pool)

        n_stocks = 0
        house_objs = []
        for h in range(1, houses + 1):
            house = House(name=f"House {h}", address=f"Main St {h}")
            for _ in range(spaces):
                space = Space(name="space")
                for _ in range(stocks):
                    n_stocks += 1
                    space.stocks.append(
                        Stock(
                            title=f"Stock {n_stocks}",
                            amount=round(rng.uniform(0, 100), 2),
                            price=Decimal(f"{rng.uniform(1, 999):.2f}"),
                            product=rng.choice(product_pool),
                        )
                    )
                house.spaces.append(space)
            house_objs.append(house)
        s.add_all(house_objs)
        s.commit()

    print(
        f"Seeded {houses} houses, {houses * spaces} spaces, {n_stocks} stocks, {products} products."
    )


if __name__ == "__main__":
    args = [int(a) for a in sys.argv[1:]]
    seed(*args)
