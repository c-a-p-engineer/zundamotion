FROM python:3.13-slim

RUN apt-get update && apt-get install -y \
    ffmpeg curl unzip git fonts-ipafont-gothic && \
    apt-get clean

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

WORKDIR /workspace
