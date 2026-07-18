#!/usr/bin/env bash
# تشغيل نظام عزوم للعروض الفنية والمالية
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt

if [ -f .env ]; then
  set -a; source .env; set +a
fi

echo "✅ نظام عزوم يعمل الآن على: http://localhost:${PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
