FROM python:3.11-slim

# Install ffmpeg
RUN apt-get update && apt-get install -y ffmpeg

# Install other dependencies
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt

CMD ["python", "bot_clean.py"]
