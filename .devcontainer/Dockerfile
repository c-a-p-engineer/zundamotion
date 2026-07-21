ARG PYTHON_IMAGE=python:3.14.6-slim-bookworm@sha256:f70215e5dbe2a47dee6d23f9c6d358bf3c148f59cce2fd165b61118e9d80f2bb
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /workspace
COPY .devcontainer/runtime.lock.json /tmp/runtime.lock.json
COPY scripts/install_locked_ffmpeg.py /usr/local/bin/install_locked_ffmpeg.py
COPY scripts/write_build_info.py /usr/local/bin/write_build_info.py
RUN python /usr/local/bin/install_locked_ffmpeg.py --lock /tmp/runtime.lock.json \
 && python /usr/local/bin/write_build_info.py --lock /tmp/runtime.lock.json
COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
 && python -m pip install --no-cache-dir -r /tmp/requirements.txt
