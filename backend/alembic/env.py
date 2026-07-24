from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 우리 앱의 설정과 모델을 연결
import app.models.ai_usage  # noqa: F401
import app.models.author_subscription  # noqa: F401
import app.models.comment  # noqa: F401
import app.models.llm_credential  # noqa: F401 — 빠지면 autogenerate가 이 테이블을 drop하려 함
import app.models.notification  # noqa: F401
import app.models.payment  # noqa: F401
import app.models.post  # noqa: F401 — 모델을 import해야 Base에 테이블이 등록됨
import app.models.status_check  # noqa: F401
import app.models.subscriber  # noqa: F401
import app.models.user  # noqa: F401
from app.core.config import settings
from app.core.database import Base

# DB 주소를 .env/기본값(settings)에서 주입 (alembic.ini에 비밀번호 안 박아도 됨)
# %를 %%로 이스케이프한다: set_main_option은 configparser를 거치는데, configparser가 %를
# 보간문법으로 해석해서, URL 인코딩된 비번(RDS 관리 비번의 특수문자 → %3E 등)이 섞이면
# "invalid interpolation syntax"로 죽는다(2026-07-24 ECS 이전 때 실측). 서빙(SQLAlchemy 직접)은
# 멀쩡했다. configparser가 읽을 때 %%를 다시 %로 되돌리므로 SQLAlchemy엔 올바른 URL이 전달된다.
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

# autogenerate가 비교할 기준: 우리 모델들의 메타데이터
target_metadata = Base.metadata

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
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
