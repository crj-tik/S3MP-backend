#!/bin/sh
set -eu

if [ "${S3MP_BOOTSTRAP_ADMIN_ENABLED:-false}" = "true" ]; then
  python -m scripts.ensure_platform_admin
fi

exec "$@"
