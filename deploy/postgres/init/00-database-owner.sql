-- The official PostgreSQL image creates POSTGRES_DB and POSTGRES_USER before
-- executing this file. Keep database ownership explicit and repeatable.
--
-- Application tables, indexes and immutable baseline permissions are owned by
-- Alembic migrations. Do not add test or business data to this directory.
ALTER DATABASE s3mp OWNER TO s3mp;
GRANT ALL PRIVILEGES ON DATABASE s3mp TO s3mp;
