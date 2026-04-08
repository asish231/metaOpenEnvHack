FROM ghcr.io/meta-pytorch/openenv-base:latest

WORKDIR /app

# Copy everything
COPY . /app/

# Install dependencies
RUN pip install --no-cache-dir .

# Expose port
EXPOSE 8000

# Run the FastAPI server
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
