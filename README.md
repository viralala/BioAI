# BioAI

BioAI is a FastAPI backend for genomics research workflows. It includes DNA translation and mutation analysis, GC-content calculations, NCBI E-utilities integration, and a Gemini-powered chat endpoint.

## Project Files

- `main.py` - importable entrypoint for the backend
- `main (3).py` - the full FastAPI application
- `requirements.txt` - Python dependencies
- `.env.example` - example environment variables
- `index (8).html` and `library.html` - frontend/static files

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and fill in any real API values you want to use.

## Environment Variables

- `GEMINI_API_KEY` - optional, required for Gemini chat responses
- `GEMINI_MODEL` - defaults to `gemini-2.0-flash`
- `NCBI_API_KEY` - optional NCBI key
- `NCBI_EMAIL` - contact email for NCBI requests
- `PORT` - server port, defaults to `8000`

## Run

Start the backend with:

```bash
python main.py
```

The server will listen on `http://localhost:8000` by default.

## API Endpoints

- `GET /` - service status and configuration
- `GET /organisms` - list supported organisms
- `GET /organism/{key}` - organism details
- `GET /gene/{organism}/{gene}` - gene lookup
- `GET /sequence/{accession}` - accession lookup
- `GET /mrna/{organism}?gene=...&limit=...` - mRNA records
- `POST /analyze/translate` - translate a DNA sequence
- `POST /analyze/mutations` - compare two sequences
- `POST /analyze/gc` - GC-content analysis
- `POST /chat` - AI-assisted genomics chat

## Notes

- The app uses a local SQLite cache file named `bioai_cache.db`.
- That cache file and other local artifacts are ignored by git.