FROM python:3.14-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY med_translation/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY med_translation /app

# Expose port for Streamlit
EXPOSE 8501

# Health check
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health

# Run Streamlit
CMD ["streamlit", "run", "app_v55.py", "--server.port=8501", "--server.address=0.0.0.0"]
