# Polisi Scraper

Core ingestion pipeline for PolisiGPT. This package crawls Malaysian government sources, deduplicates by SHA256, and stores files in DigitalOcean Spaces using the key pattern `gov-my/{agency}/{year-month}/filename.ext`.

## Quick Start

1. Create a Python 3.11 virtual environment.
2. Install dependencies:
   ```bash
   pip install -e .
   ```
3. Copy environment template and fill credentials:
   ```bash
   cp .env.example .env
   ```
4. Run tests:
   ```bash
   python -m pytest
   ```

## Required Environment Variables

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `DO_SPACES_KEY`
- `DO_SPACES_SECRET`
- `DO_SPACES_BUCKET`
- `DO_SPACES_REGION`
- `DO_SPACES_ENDPOINT`

See `.env.example` for optional runtime knobs.
