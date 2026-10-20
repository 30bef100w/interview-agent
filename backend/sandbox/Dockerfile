FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    g++ default-jdk-headless golang-go \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/runner
COPY app/services/code_runner.py app/services/code_lang.py app/services/scratch_io.py \
     app/services/code_process.py app/services/code_worker.py ./app/services/
ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 PYTHONUTF8=1 \
    JAVA_TOOL_OPTIONS="-Xmx192m -XX:ReservedCodeCacheSize=32m -XX:MaxMetaspaceSize=128m -XX:ActiveProcessorCount=1" \
    GO111MODULE=off GOMAXPROCS=1 HOME=/tmp
USER 10001:10001
WORKDIR /work
ENTRYPOINT ["python", "-I", "-c", "import sys; sys.path.insert(0, '/opt/runner'); from app.services.code_worker import main; main()"]
