FROM python:3.12-alpine

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY exporter.py .

EXPOSE 9610
USER nobody:nobody
ENTRYPOINT ["python", "/app/exporter.py"]
