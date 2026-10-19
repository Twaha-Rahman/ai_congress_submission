FROM python:3.11.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# Reproducible dependency set generated with `pip freeze` in the project venv.
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt

# Application code and immutable demo configuration.  Runtime databases, keys,
# environment secrets and raw/synthetic source material are never baked into the
# image: offices receive only their own replay/cache assets through compose mounts,
# and the gateway receives none.
COPY meridian ./meridian
COPY config ./config
COPY pyproject.toml Makefile README.md ./

EXPOSE 8000

# Both entry points read REGION/PORT from the environment.
CMD ["python", "-m", "meridian.office_api.main"]
