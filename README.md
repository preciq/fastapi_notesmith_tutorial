# To execute uvicorn server: 

```bash
uvicorn src.notesmith.main:app --reload --port 8000
```

# Alembic specific

1. **Modify SQLAlchemy model** (add a column, change a type, add a table).
2. **Generate a migration**: `alembic revision --autogenerate -m "Description of change"`
3. **Review the generated script** in `alembic/versions/`.
4. **Apply it**: `alembic upgrade head`