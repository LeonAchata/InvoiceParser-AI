# InvoiceProcessing – AI-Powered Invoice Pipeline

Pipeline for processing PDF invoices, extracting data with LLM, and delivering results ready for storage or Excel export. Includes API (FastAPI), lightweight frontend, and a pipeline orchestrated with LangGraph.

## What does it do?

- Validates and reads invoice PDFs (up to 10 MB)
- Extracts text from the first pages using PyMuPDF/pdfplumber/PyPDF2 based on availability
- Cleans and normalizes text
- Uses an LLM (OpenAI) with specialized prompts for Peruvian invoices and returns JSON with: customer data, items, payment method, currency, subtotal, VAT (IGV), total, and withholding (detracción)
- Allows downloading an Excel file with results and saving to PostgreSQL (optional)

## Technology Stack

- Backend: FastAPI, Uvicorn
- Orchestration: LangGraph (StateGraph + MemorySaver)
- LLM: OpenAI (gpt-4o-mini by default)
- PDF: PyMuPDF (fitz), pdfplumber, PyPDF2
- Data/Validation: Pydantic, pydantic-settings
- DB: asyncpg (PostgreSQL) – optional
- Excel: openpyxl
- Frontend: Vanilla HTML/CSS/JS
- Container: Docker (multi-stage)

## Architecture and Pipeline Flow

File: `pipeline.py` (LangGraph)

Sequential node flow:
1) document_ingestion → 2) text_extraction → 3) text_cleaning → 4) llm → END

Nodes (folder `nodes/`):
- Node 1 – Ingestion (`ingestion.py`)
	- Validates existence, size (<= settings.max_pdf_size_mb), PDF integrity, and extractable text
	- Determines the most reliable extraction method (PyMuPDF/pdfplumber/PyPDF2) and stores metadata in `logging.debug_info`
- Node 2 – Extraction (`extraction.py`)
	- Extracts text from up to 3 pages with the validated method
	- Saves raw text in `state.text_content.raw_text` and statistics
- Node 3 – Cleaning (`cleaning.py`)
	- Normalizes capitalization and whitespace; calculates cleaning metrics
	- Saves cleaned text in `state.text_content.cleaned_text`
- Node 4 – LLM (`llm.py`)
	- Generates prompts (`models/prompts.py`) and calls OpenAI
	- Parses JSON and stores in `state.extracted_data`. Updates metrics and sets `status=COMPLETED`

## Pipeline State

Main model: `models/state.py` (Pydantic)
- document_info: file_path, filename, file_size
- text_content: raw_text, cleaned_text
- processing_control: processing_stage, status (PROCESSING/COMPLETED/FAILED)
- metrics: tokens_used, processing_time, cost_estimate, llm_model
- quality: confidence_score, completeness_score
- logging: messages, errors, warnings, debug_info
- extracted_data: dict with LLM result (customer, items, totals, withholding)

Configuration: `models/settings.py`
- Reads `.env`. Requires variables: `OPENAI_API_KEY` and `DATABASE_URL` (if using DB)
- Others: `llm_model`, `llm_temperature`, PDF limits, etc.

## API (FastAPI)

File: `main.py`
- POST /upload: Upload PDF. Returns `job_id` and initial status. Processing runs in background
- GET /status/{job_id}: Job status (PENDING/PROCESSING/COMPLETED/FAILED)
- GET /result/{job_id}: Complete result when COMPLETED
- POST /guardar-factura: Saves invoice to PostgreSQL received from frontend. Requires DB
- POST /guardar-factura-excel: Generates and downloads Excel with submitted data
- GET /facturas: Lists saved invoices (paginated). Requires DB

Notes:
- The app can start without DB; save/list endpoints will return 503 if no connection
- The Dockerfile defines a healthcheck at `/health`; add that endpoint if needed or adjust the healthcheck

## Lightweight Frontend

Path: `frontend/`
- `index.html`: interface with drag-and-drop or PDF selection, progress bar, and editable form
- `script.js`: calls API (`/upload`, `/status`, `/result`) and populates form with `extracted_data`. Allows Excel download via `/guardar-factura-excel`
- `styles.css`: modern and responsive styles

Usage: open `frontend/index.html` in browser with backend running at `http://localhost:8000` (CORS enabled for dev)

## Requirements and Configuration

Prerequisites:
- Python 3.11+
- OpenAI API key (format `sk-...`)
- PostgreSQL (optional, for persistence)

Minimum `.env` file in root:
```
OPENAI_API_KEY=sk-XXXX
DATABASE_URL=postgresql://user:pass@host:5432/dbname  # optional if not using DB
TEMP_DIR=./temp
LLM_MODEL=gpt-4o-mini
```

## Local Execution (Windows PowerShell)

Install dependencies and start API:
```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Open frontend:
- Double-click `frontend/index.html` or serve with a static server

## Docker

Build and run:
```powershell
docker build -t invoice-processing:latest .
docker run -e OPENAI_API_KEY=sk-XXXX -e DATABASE_URL=postgresql://user:pass@host:5432/dbname -p 8000:8000 invoice-processing:latest
```

## Folder Structure (Summary)

```
.
├── main.py                # FastAPI API
├── pipeline.py            # LangGraph orchestration
├── database.py            # Async PostgreSQL manager (optional)
├── models/                # State, settings, prompts
├── nodes/                 # Nodes: ingestion, extraction, cleaning, llm
├── utils/                 # PDF, LLM, Excel, API helpers
├── frontend/              # Simple UI (HTML/JS/CSS)
├── requirements.txt       # Dependencies
├── Dockerfile             # Deployment image
└── temp/                  # Temporary files
```

## Notes and Limitations

- Up to 3 pages per PDF are processed in current extraction (adjustable)
- LLM responds only with JSON; if PDF has no extractable text, job fails with clear message
- For persistence, assumes schema with `facturas` and `factura_items` tables (create before using `guardar-factura`)

## Detailed Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend (HTML/JS)                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ Upload   │  │ Progress │  │   Form   │  │ Download │  │
│  │   PDF    │─→│   Bar    │─→│  Editor  │─→│  Excel   │  │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  │
└─────────────────────────┬───────────────────────────────────┘
                          │ HTTP/JSON
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Backend (main.py)                │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  POST /upload              GET /status/{job_id}      │  │
│  │  GET /result/{job_id}      GET /facturas            │  │
│  │  POST /guardar-factura     POST /guardar-factura-   │  │
│  │                                  excel               │  │
│  └──────────────────────────────────────────────────────┘  │
│                          │                                  │
│                          ▼                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │         Background Task Manager                      │  │
│  │         (AsyncIO + Job Queue)                        │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              LangGraph Pipeline (pipeline.py)               │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │                    StateGraph                         │  │
│  │                                                       │  │
│  │   START                                               │  │
│  │     ↓                                                 │  │
│  │   ┌─────────────────────┐                           │  │
│  │   │  Node 1: Ingestion  │                           │  │
│  │   │  - Validate PDF     │                           │  │
│  │   │  - Check size       │                           │  │
│  │   │  - Verify integrity │                           │  │
│  │   └──────────┬──────────┘                           │  │
│  │              ↓                                        │  │
│  │   ┌─────────────────────┐                           │  │
│  │   │  Node 2: Extraction │                           │  │
│  │   │  - Extract text     │                           │  │
│  │   │  - PyMuPDF/pdfplumb │                           │  │
│  │   │  - Up to 3 pages    │                           │  │
│  │   └──────────┬──────────┘                           │  │
│  │              ↓                                        │  │
│  │   ┌─────────────────────┐                           │  │
│  │   │  Node 3: Cleaning   │                           │  │
│  │   │  - Normalize text   │                           │  │
│  │   │  - Remove noise     │                           │  │
│  │   │  - Calculate metrics│                           │  │
│  │   └──────────┬──────────┘                           │  │
│  │              ↓                                        │  │
│  │   ┌─────────────────────┐                           │  │
│  │   │  Node 4: LLM        │                           │  │
│  │   │  - Generate prompts │                           │  │
│  │   │  - Call OpenAI      │                           │  │
│  │   │  - Parse JSON       │                           │  │
│  │   │  - Extract data     │                           │  │
│  │   └──────────┬──────────┘                           │  │
│  │              ↓                                        │  │
│  │            END                                        │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────┬───────────────────────────────────┘
                          │
            ┌─────────────┴──────────────┐
            ▼                            ▼
┌───────────────────────┐    ┌─────────────────────┐
│   OpenAI API          │    │  PostgreSQL DB      │
│   (gpt-4o-mini)       │    │  (Optional)         │
│                       │    │                     │
│  - Generate JSON      │    │  - facturas table   │
│  - Extract fields     │    │  - factura_items    │
│  - Structured output  │    │  - Relationships    │
└───────────────────────┘    └─────────────────────┘
```

## Data Flow Example

```
1. User uploads PDF (5 MB)
   └─> POST /upload
       └─> Returns: {"job_id": "abc123", "status": "PENDING"}

2. Background task starts
   └─> Job status: PROCESSING
       └─> Node 1: Validates PDF ✓
       └─> Node 2: Extracts 2000 chars ✓
       └─> Node 3: Cleans to 1800 chars ✓
       └─> Node 4: LLM extracts structured data ✓

3. Job completes
   └─> Job status: COMPLETED
       └─> GET /result/abc123
           └─> Returns:
               {
                 "extracted_data": {
                   "cliente": {
                     "razon_social": "ABC Corp",
                     "ruc": "20123456789",
                     "direccion": "Av. Example 123"
                   },
                   "items": [
                     {
                       "descripcion": "Product A",
                       "cantidad": 10,
                       "precio_unitario": 100.00,
                       "valor_total": 1000.00
                     }
                   ],
                   "forma_pago": "Contado",
                   "moneda": "PEN",
                   "subtotal": 1000.00,
                   "igv": 180.00,
                   "total": 1180.00,
                   "detraccion": {
                     "aplica": true,
                     "porcentaje": 10,
                     "monto": 118.00
                   }
                 },
                 "metrics": {
                   "tokens_used": 2500,
                   "processing_time": 3.45,
                   "cost_estimate": 0.0025,
                   "llm_model": "gpt-4o-mini"
                 }
               }

4. User edits form in frontend
   └─> Downloads Excel
       └─> POST /guardar-factura-excel
           └─> Returns: invoice_abc123.xlsx

5. User saves to database (optional)
   └─> POST /guardar-factura
       └─> Inserts into PostgreSQL
       └─> Returns: {"factura_id": 42, "status": "saved"}
```

## State Schema (Detailed)

```python
# models/state.py

class InvoiceState(BaseModel):
    """Complete pipeline state"""
    
    # Document information
    document_info: dict = {
        "file_path": str,      # Path to uploaded PDF
        "filename": str,       # Original filename
        "file_size": int,      # Size in bytes
        "upload_time": str     # ISO timestamp
    }
    
    # Extracted text content
    text_content: dict = {
        "raw_text": str,       # Unprocessed text
        "cleaned_text": str,   # Normalized text
        "char_count": int,     # Character count
        "word_count": int      # Word count
    }
    
    # Processing control
    processing_control: dict = {
        "processing_stage": str,  # Current node
        "status": str,            # PROCESSING/COMPLETED/FAILED
        "started_at": str,        # Start timestamp
        "completed_at": str       # End timestamp
    }
    
    # Usage metrics
    metrics: dict = {
        "tokens_used": int,       # Total tokens
        "processing_time": float, # Seconds
        "cost_estimate": float,   # USD
        "llm_model": str          # Model used
    }
    
    # Quality assessment
    quality: dict = {
        "confidence_score": float,    # 0.0-1.0
        "completeness_score": float   # 0.0-1.0
    }
    
    # Logging and debugging
    logging: dict = {
        "messages": list[str],    # Info messages
        "errors": list[str],      # Error messages
        "warnings": list[str],    # Warnings
        "debug_info": dict        # Debug metadata
    }
    
    # Extracted invoice data (LLM output)
    extracted_data: dict = {
        "cliente": {
            "razon_social": str,
            "ruc": str,
            "direccion": str
        },
        "items": [
            {
                "descripcion": str,
                "cantidad": float,
                "precio_unitario": float,
                "valor_total": float
            }
        ],
        "forma_pago": str,
        "moneda": str,
        "subtotal": float,
        "igv": float,
        "total": float,
        "detraccion": {
            "aplica": bool,
            "porcentaje": float,
            "monto": float
        }
    }
```

## API Endpoints (Detailed)

### 1. POST /upload

Upload and process invoice PDF.

**Request:**
```bash
curl -X POST http://localhost:8000/upload \
  -F "file=@invoice.pdf"
```

**Response:**
```json
{
  "job_id": "abc123",
  "status": "PENDING",
  "filename": "invoice.pdf",
  "file_size": 524288,
  "message": "PDF uploaded successfully. Processing started."
}
```

### 2. GET /status/{job_id}

Check processing status.

**Request:**
```bash
curl http://localhost:8000/status/abc123
```

**Response:**
```json
{
  "job_id": "abc123",
  "status": "PROCESSING",
  "stage": "text_extraction",
  "progress": 50,
  "message": "Extracting text from PDF..."
}
```

### 3. GET /result/{job_id}

Get complete results (only when COMPLETED).

**Request:**
```bash
curl http://localhost:8000/result/abc123
```

**Response:**
```json
{
  "job_id": "abc123",
  "status": "COMPLETED",
  "extracted_data": { ... },
  "metrics": {
    "tokens_used": 2500,
    "processing_time": 3.45,
    "cost_estimate": 0.0025
  },
  "quality": {
    "confidence_score": 0.92,
    "completeness_score": 0.88
  }
}
```

### 4. POST /guardar-factura

Save invoice to PostgreSQL.

**Request:**
```bash
curl -X POST http://localhost:8000/guardar-factura \
  -H "Content-Type: application/json" \
  -d '{
    "cliente": {...},
    "items": [...],
    "totales": {...}
  }'
```

**Response:**
```json
{
  "factura_id": 42,
  "status": "saved",
  "message": "Invoice saved successfully"
}
```

### 5. POST /guardar-factura-excel

Generate and download Excel file.

**Request:**
```bash
curl -X POST http://localhost:8000/guardar-factura-excel \
  -H "Content-Type: application/json" \
  -d '{...}' \
  --output invoice.xlsx
```

**Response:** Binary Excel file

### 6. GET /facturas

List saved invoices (paginated).

**Request:**
```bash
curl "http://localhost:8000/facturas?page=1&limit=10"
```

**Response:**
```json
{
  "total": 42,
  "page": 1,
  "limit": 10,
  "facturas": [
    {
      "id": 42,
      "razon_social": "ABC Corp",
      "ruc": "20123456789",
      "total": 1180.00,
      "created_at": "2025-01-15T10:30:00Z"
    }
  ]
}
```

## Environment Variables (Complete)

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `OPENAI_API_KEY` | OpenAI API key | - | Yes |
| `DATABASE_URL` | PostgreSQL connection URL | - | No |
| `TEMP_DIR` | Temporary files directory | ./temp | No |
| `LLM_MODEL` | OpenAI model name | gpt-4o-mini | No |
| `LLM_TEMPERATURE` | Sampling temperature | 0.1 | No |
| `MAX_PDF_SIZE_MB` | Maximum PDF size | 10 | No |
| `MAX_PAGES_EXTRACT` | Max pages to extract | 3 | No |
| `ENABLE_CACHE` | Enable response caching | false | No |
| `LOG_LEVEL` | Logging level | INFO | No |
| `CORS_ORIGINS` | Allowed CORS origins | * | No |

## Database Schema

### Table: facturas

```sql
CREATE TABLE facturas (
    id SERIAL PRIMARY KEY,
    job_id VARCHAR(100) UNIQUE,
    razon_social VARCHAR(255) NOT NULL,
    ruc VARCHAR(11) NOT NULL,
    direccion TEXT,
    forma_pago VARCHAR(50),
    moneda VARCHAR(3),
    subtotal DECIMAL(12, 2),
    igv DECIMAL(12, 2),
    total DECIMAL(12, 2) NOT NULL,
    detraccion_aplica BOOLEAN DEFAULT false,
    detraccion_porcentaje DECIMAL(5, 2),
    detraccion_monto DECIMAL(12, 2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_facturas_ruc ON facturas(ruc);
CREATE INDEX idx_facturas_created_at ON facturas(created_at);
```

### Table: factura_items

```sql
CREATE TABLE factura_items (
    id SERIAL PRIMARY KEY,
    factura_id INTEGER NOT NULL REFERENCES facturas(id) ON DELETE CASCADE,
    descripcion TEXT NOT NULL,
    cantidad DECIMAL(10, 2) NOT NULL,
    precio_unitario DECIMAL(12, 2) NOT NULL,
    valor_total DECIMAL(12, 2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_items_factura_id ON factura_items(factura_id);
```

## Error Handling

The pipeline handles errors gracefully:

```python
# Example error responses

# PDF too large
{
  "status": "FAILED",
  "error": "PDF size exceeds 10 MB limit",
  "error_code": "PDF_TOO_LARGE"
}

# No extractable text
{
  "status": "FAILED",
  "error": "PDF contains no extractable text",
  "error_code": "NO_TEXT_FOUND"
}

# LLM parsing error
{
  "status": "FAILED",
  "error": "Failed to parse LLM response",
  "error_code": "LLM_PARSE_ERROR",
  "raw_response": "..."
}

# Database connection error
{
  "status": "ERROR",
  "error": "Database not available",
  "error_code": "DB_UNAVAILABLE"
}
```

## Performance Optimization

### Caching (Optional)

Enable response caching for repeated PDFs:

```python
# .env
ENABLE_CACHE=true
CACHE_TTL=3600  # 1 hour

# Results cached by PDF hash
# Reduces costs for duplicate invoices
```

### Batch Processing

Process multiple invoices:

```python
import asyncio
from pathlib import Path

async def batch_process(pdf_dir: Path):
    pdfs = list(pdf_dir.glob("*.pdf"))
    tasks = [process_invoice(pdf) for pdf in pdfs]
    results = await asyncio.gather(*tasks)
    return results
```

### Resource Limits

Configure in `models/settings.py`:

```python
class Settings(BaseSettings):
    max_concurrent_jobs: int = 5
    max_pdf_size_mb: int = 10
    max_pages_extract: int = 3
    request_timeout: int = 60
```

## Testing

Run tests:

```bash
# Install test dependencies
pip install pytest pytest-asyncio httpx

# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html
```

Example test:

```python
# test_pipeline.py

import pytest
from pipeline import create_pipeline
from models.state import InvoiceState

@pytest.mark.asyncio
async def test_ingestion_node():
    pipeline = create_pipeline()
    state = InvoiceState(
        document_info={"file_path": "test_invoice.pdf"}
    )
    result = await pipeline.ainvoke(state)
    assert result["processing_control"]["status"] == "COMPLETED"
    assert "extracted_data" in result
```

## Deployment

### Docker Compose (Production)

```yaml
# docker-compose.yml

version: '3.8'

services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - DATABASE_URL=postgresql://postgres:password@db:5432/invoices
      - LLM_MODEL=gpt-4o-mini
    depends_on:
      - db
    volumes:
      - ./temp:/app/temp
    restart: unless-stopped

  db:
    image: postgres:15-alpine
    environment:
      - POSTGRES_DB=invoices
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

volumes:
  postgres_data:
```

### AWS Lambda (Serverless)

Use Mangum adapter:

```python
# main.py
from mangum import Mangum

app = FastAPI()
# ... your routes ...

handler = Mangum(app)  # AWS Lambda handler
```

### Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: invoice-processing
spec:
  replicas: 3
  selector:
    matchLabels:
      app: invoice-processing
  template:
    metadata:
      labels:
        app: invoice-processing
    spec:
      containers:
      - name: api
        image: invoice-processing:latest
        env:
        - name: OPENAI_API_KEY
          valueFrom:
            secretKeyRef:
              name: openai-secret
              key: api-key
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
```

## Monitoring and Logging

### Structured Logging

```python
# utils/logger.py

import logging
import json

class StructuredLogger:
    def log_event(self, event_type: str, data: dict):
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "event": event_type,
            **data
        }
        logging.info(json.dumps(log_entry))

# Usage
logger.log_event("pdf_uploaded", {
    "job_id": "abc123",
    "filename": "invoice.pdf",
    "size": 524288
})
```

### Metrics Tracking

```python
# Track key metrics
{
  "total_jobs": 1000,
  "successful_jobs": 950,
  "failed_jobs": 50,
  "average_processing_time": 3.2,
  "total_cost": 12.45,
  "average_confidence": 0.89
}
```

## Troubleshooting

### Common Issues

**1. PDF extraction fails**
```
Error: No text extractable from PDF
Solution: PDF might be image-based. Add OCR support with pytesseract.
```

**2. LLM returns invalid JSON**
```
Error: Failed to parse LLM response
Solution: Check prompt engineering. Add JSON schema validation.
```

**3. Database connection timeout**
```
Error: asyncpg.exceptions.ConnectionDoesNotExistError
Solution: Verify DATABASE_URL. Check network connectivity.
```

**4. High API costs**
```
Issue: Unexpected OpenAI charges
Solution: Enable caching. Use cheaper model (gpt-4o-mini).
```

## Roadmap

### Planned Features

- 🔜 OCR support for image-based PDFs (Tesseract)
- 🔜 Multi-language support (English, Spanish invoices)
- 🔜 Batch processing API endpoint
- 🔜 WebSocket for real-time progress
- 🔜 Invoice validation rules (SUNAT compliance)
- 🔜 Export to multiple formats (CSV, JSON, XML)
- 🔜 Integration with accounting software (QuickBooks, Xero)
- 🔜 Mobile app (React Native)

## Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project was developed for educational purposes at PUCP.

## Author

**LeonAchataS** · Project: InvoiceProcessing

## References

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [OpenAI API Documentation](https://platform.openai.com/docs/)
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [PyMuPDF Documentation](https://pymupdf.readthedocs.io/)

---

**Need help?** Open an issue on GitHub or contact the development team.
