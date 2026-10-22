FROM ghcr.io/d4vinci/scrapling:latest
WORKDIR /app
RUN python -m pip install --no-cache-dir neo4j
COPY job.py .
ENTRYPOINT ["python", "/app/job.py"]
