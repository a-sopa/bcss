FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./cloud_honeypot_ai/requirements.txt
RUN pip install --no-cache-dir -r ./cloud_honeypot_ai/requirements.txt

COPY . ./cloud_honeypot_ai

ENV PYTHONUNBUFFERED=1

EXPOSE 8888 2222 8080 2323

CMD ["python3", "-m", "cloud_honeypot_ai.run_honeypot", "start", "--ssh-port", "2222", "--tcp-port", "2323", "--http-port", "8080", "--dashboard-port", "8888"]
