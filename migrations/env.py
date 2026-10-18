from alembic import context
from invest.db import engine, Base
from invest import models

config = context.config
target_metadata = Base.metadata


def run():
    with engine().connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run()
