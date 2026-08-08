# run this from the same directory/venv you run create_tables.py from
from app.core.database import Base
from app.models.user import Profile
from app.models.target import Target
from app.models.food_log import FoodLog

print(sorted(Base.metadata.tables.keys()))