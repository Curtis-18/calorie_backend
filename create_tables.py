import asyncio
from app.core.database import engine, Base
from app.models.user import Profile
from app.models.target import Target
from app.models.food_log import FoodLog
from app.models.insights_cache import InsightsCache

print(sorted(Base.metadata.tables.keys()))  # add this line

async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[Profile.__table__, Target.__table__, FoodLog.__table__, InsightsCache.__table__])
    print("tables created")

asyncio.run(main())