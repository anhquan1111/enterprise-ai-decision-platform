import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Cho phép chạy `uv run alembic ...` từ gốc repo mà không cần cài project như một
# package — cùng cách các script trong scripts/ đã làm.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import get_settings  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Không dùng ORM (xem src/db.py) nên không có model MetaData nào để autogenerate
# diff theo — mọi migration ở đây viết tay, raw SQL, đúng nguyên tắc "đọc được,
# giải thích được, đọc được query plan" đã áp dụng cho toàn bộ src/db.py.
target_metadata = None

# Lấy connection string từ đúng một nguồn sự thật (src/config.py, đọc .env) thay vì
# lặp lại cấu hình trong alembic.ini — hai nơi cấu hình DB là cách lệch cấu hình xảy
# ra khi chỉ một nơi được cập nhật.
_settings = get_settings()
_db_url = _settings.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
# set_main_option ghi qua configparser, vốn dùng "%" cho cú pháp interpolation —
# database_url có "%20"/"%3D" (URL-encoded) nên phải nhân đôi "%" trước khi ghi,
# nếu không configparser sẽ báo "invalid interpolation syntax".
config.set_main_option("sqlalchemy.url", _db_url.replace("%", "%%"))

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
