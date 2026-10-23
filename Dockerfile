FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /job
RUN pip install --no-cache-dir "scrapling[all]" neo4j \
 && scrapling install
COPY job.py .
ENTRYPOINT ["python","/job/job.py"]
