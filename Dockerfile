FROM python:3.14-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for layer caching)
COPY med_translation/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY med_translation ./

# Create .streamlit directory for config
RUN mkdir -p ~/.streamlit

# Create streamlit config (disable browser auto-open)
RUN echo "\
[browser]\n\
gatherUsageStats = false\n\
serverAddress = \"0.0.0.0\"\n\
" > ~/.streamlit/config.toml

# Expose port for Streamlit (Railway default 8000, but Streamlit uses 8501)
EXPOSE 8501

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# Run Streamlit app
CMD ["streamlit", "run", "app_v55.py", "--server.port=8501", "--server.address=0.0.0.0", "--client.showErrorDetails=true"]
