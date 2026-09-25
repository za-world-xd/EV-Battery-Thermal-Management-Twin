FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml requirements.txt ./
COPY simulator ./simulator
COPY app ./app
COPY .streamlit ./.streamlit
RUN pip install --no-cache-dir . && useradd --create-home celltwin
USER celltwin
EXPOSE 8000 8501
CMD ["python", "-m", "uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
