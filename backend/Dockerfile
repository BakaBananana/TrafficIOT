FROM python:3.12-slim

WORKDIR /app

# Install system deps for SUMO (optional in container)
RUN apt-get update && apt-get install -y --no-install-recommends \
    sumo sumo-tools \
    && rm -rf /var/lib/apt/lists/*

ENV SUMO_HOME=/usr/share/sumo

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
