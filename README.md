# Market Analysis Tool

A real-time market analysis tool that provides stock information, technical analysis, and market news.

## Features

- Real-time market indices tracking (S&P 500, NASDAQ, Dow Jones)
- Stock technical analysis with indicators
- Market news aggregation
- Stock comparison tools
- Text-based visualization

## Deployment Options

### 1. Docker Deployment (Recommended)

```bash
# Build and start the container
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the container
docker-compose down
```

The application will be available at `http://your-server-ip:8000`

### 2. Manual Deployment

1. Create a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run with Gunicorn:
```bash
gunicorn --config gunicorn_config.py wsgi:app
```

## Environment Variables

Create a `.env` file with the following variables:
```
FLASK_ENV=production
FLASK_APP=app.py
```

## Directory Structure

```
.
├── app.py              # Flask application
├── wsgi.py            # WSGI entry point
├── requirements.txt    # Python dependencies
├── gunicorn_config.py # Gunicorn configuration
├── Dockerfile         # Docker configuration
├── docker-compose.yml # Docker Compose configuration
├── src/              # Source code
├── static/           # Static files
├── templates/        # HTML templates
├── data/            # Data storage
└── logs/            # Application logs
```

## Maintenance

- Logs are stored in the `logs` directory
- Cache data is stored in `data/cache`
- Monitor the application using the health check endpoint: `/health`

## Security Notes

- The application runs as a non-root user in Docker
- Rate limiting is enabled
- Request size limits are configured
- Environment variables are used for sensitive data 