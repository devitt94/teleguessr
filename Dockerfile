FROM python:3.12-slim

# Install uv
RUN pip install uv

# Set working directory
WORKDIR /app

# Copy project files
COPY . .

COPY data/league.json data/league.json

# Install dependencies using uvsudo systemctl start docker
RUN uv sync --frozen

# Run bot
CMD ["uv", "run", "main.py"]
