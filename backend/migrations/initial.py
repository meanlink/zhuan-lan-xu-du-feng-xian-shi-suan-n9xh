from sqlalchemy import text, inspect
from src.config.database import Base, engine
from src import models  # noqa: F401  确保全部模型已注册


# 既有部署平滑升级：create_all 只建新表，不会给旧表补列。
# 这里对新增列做幂等补齐，列类型与模型声明保持一致。
def _ensure_columns():
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    additions = {
        'jobs': [
            ('audience_build_id', 'INTEGER'),
            ('eligibility', "VARCHAR(20) DEFAULT 'eligible'"),
            ('invalidate_reason', 'VARCHAR(500)'),
        ],
    }
    with engine.begin() as conn:
        for table, cols in additions.items():
            if table not in existing_tables:
                continue
            present = {c['name'] for c in inspector.get_columns(table)}
            for name, ddl_type in cols:
                if name in present:
                    continue
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl_type}'))


def migrate():
    Base.metadata.create_all(engine)
    _ensure_columns()


if __name__ == '__main__':
    migrate()
