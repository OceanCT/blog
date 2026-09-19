FROM python:3.12-slim
RUN pip install --no-cache-dir ray==2.58.0
WORKDIR /lab
COPY demo.py .
CMD ["python", "-u", "demo.py"]
