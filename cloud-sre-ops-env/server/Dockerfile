FROM python:3.10-slim

WORKDIR /app

RUN pip install openenv-core fastapi uvicorn

COPY . /app

CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
