FROM python:3.12-slim

WORKDIR /code
ENV PYTHONPATH=/code

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY app/ ./app/
COPY alembic.ini ./

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
