FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.lock /opt/presidio/requirements.lock
RUN pip install --require-hashes -r /opt/presidio/requirements.lock
COPY server.py /opt/presidio/server.py
EXPOSE 5002
CMD ["python", "/opt/presidio/server.py"]
