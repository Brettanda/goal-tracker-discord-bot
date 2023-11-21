# Temp Stage
FROM python:3.8 AS build

WORKDIR /usr/src/app

COPY ./requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
  pip install -r requirements.txt
# Final Stage
FROM python:3.8-slim

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1

# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1

WORKDIR /usr/src/app

COPY --from=build /usr/local/lib/python3.8/site-packages /usr/local/lib/python3.8/site-packages


# Just in case https://hynek.me/articles/docker-signals/
STOPSIGNAL SIGINT

ENTRYPOINT exec python3 index.py
