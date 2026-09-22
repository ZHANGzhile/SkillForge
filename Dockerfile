FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
COPY skillforge ./skillforge
RUN pip install --no-cache-dir .
COPY configs ./configs
CMD ["uvicorn", "skillforge.api:app", "--host", "0.0.0.0", "--port", "8080"]
