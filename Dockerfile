FROM python:3.11.12-slim
WORKDIR /app
COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt
COPY . .
ENV APPDATA=/data
EXPOSE 8881
CMD ["uvicorn", "web.server:app", "--host", "0.0.0.0", "--port", "8881"]
