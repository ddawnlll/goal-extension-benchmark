FROM python:3.12-slim

WORKDIR /relay
COPY relay.py /relay/relay.py
ENV PYTHONUNBUFFERED=1
EXPOSE 9091
CMD ["python3", "/relay/relay.py"]
