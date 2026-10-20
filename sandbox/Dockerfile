# Analyst workstation for benchmark runs: Python with common data tools, no network at run time.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends unzip p7zip-full \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir pandas==2.2.3 lxml==5.3.0 inflate64==1.0.4 \
 && useradd --create-home analyst \
 && mkdir -p /work && chown analyst /work
USER analyst
WORKDIR /work
