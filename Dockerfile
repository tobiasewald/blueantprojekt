FROM python:3.10-slim

WORKDIR /workspace

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and default configuration files
COPY app/ ./app/
COPY config.yaml .
COPY prompts.yaml .
COPY static/ ./static/


# Create directory for reports volume mount
RUN mkdir -p reports

# Expose port 8000
EXPOSE 8000

# Run FastAPI app with uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
