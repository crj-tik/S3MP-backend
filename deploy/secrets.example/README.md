# Production secret files

Create the actual directory outside the repository, set its owner to the
deployment account, and use `chmod 700 <directory>` plus `chmod 600 <files>`.
Each file contains exactly one value and an optional final newline.

| File | Content |
| --- | --- |
| `postgres_password` | PostgreSQL password for the `s3mp` database user |
| `redis_password` | Redis `requirepass` value |
| `database_url` | `postgresql+asyncpg://s3mp:<url-encoded-postgres-password>@postgres:5432/s3mp` |
| `redis_url` | `redis://:<url-encoded-redis-password>@redis:6379/0` |
| `s3_access_key` | Online S3 service access key with access limited to the configured bucket |
| `s3_secret_key` | Corresponding online S3 service secret key |
| `api_key_pepper` | At least 32 random bytes, for example `openssl rand -base64 48` |

The URL passwords must be URL-encoded. Provision the online S3 bucket and its
least-privilege credentials before deployment; this Compose stack does not
create or administer the bucket. Keep these files out of Git, build contexts,
screenshots, and shell history.
