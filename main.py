"""FastAPI application for AI Product Generator."""

import logging
import os
import random

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from agent.image import generate_poster
from api_models import ErrorResponse, ProductGenerateRequest, ProductGenerateResponse
from core.config import load_full_config, save_full_config, settings
from core.constants import CORS_ALLOW_ORIGINS
from services.product_service import ProductService
from utils.logging_config import setup_logging

from fastapi.templating import Jinja2Templates


# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Initialize service
product_service = ProductService()

from core.manager import ConnectionManager
from services.bulk_upload_service import BulkUploadService
from fastapi import (
    WebSocket,
    WebSocketDisconnect,
    UploadFile,
    File,
    Form,
    BackgroundTasks,
)
from fastapi.responses import FileResponse
import pandas as pd
import json
from io import BytesIO

manager = ConnectionManager()
bulk_service = BulkUploadService(manager)


# Initialize FastAPI app
app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    description="AI-powered product content generation API",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
from fastapi.staticfiles import StaticFiles

app.mount("/static", StaticFiles(directory="static"), name="static")

# Mount media directories if they exist
if os.path.exists("media"):
    app.mount("/media", StaticFiles(directory="media"), name="media")

# Templates
templates = Jinja2Templates(directory="static")


@app.get("/", tags=["Root"])
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.post("/upload-excel", tags=["Bulk Upload"])
async def upload_excel(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    email: str = Form(...),
    password: str = Form(...),
    image_search_site: str = Form(""),
    additional_search: str = Form("false"),
):
    """
    Upload Excel file for bulk product generation.
    """
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(
            status_code=400, detail="Faqat Excel fayllar qabul qilinadi (.xlsx, .xls)"
        )

    # Convert additional_search string to boolean
    additional_search_bool = additional_search.lower() == "true"

    # Start processing in background
    background_tasks.add_task(
        bulk_service.process_excel,
        file=file,
        email=email,
        password=password,
        image_search_site=image_search_site if image_search_site else None,
        additional_search=additional_search_bool,
    )

    return {
        "message": "Fayl qabul qilindi. Jarayon boshlandi.",
        "filename": file.filename,
    }


# MXIK Codes CRUD Endpoints
EXCEL_FILE_PATH = "api/mxik-codes.xlsx"


@app.get("/mxik-codes-page", tags=["MXIK Management"])
async def mxik_codes_page(request: Request):
    """Render the MXIK management page."""
    return templates.TemplateResponse("mxik.html", {"request": request})


# Config CRUD (admin)
@app.get("/config", tags=["Config Admin"])
async def config_page(request: Request):
    """Config boshqaruv sahifasi."""
    return templates.TemplateResponse("admin-config.html", {"request": request})


@app.get("/api/config", tags=["Config Admin"])
async def get_config():
    """Get full config.json."""
    try:
        return load_full_config()
    except Exception as e:
        logger.error(f"Error reading config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/config", tags=["Config Admin"])
async def update_config(request: Request):
    """Update full config.json."""
    try:
        body = await request.json()
        save_full_config(body)
        return {"message": "Config saqlandi"}
    except Exception as e:
        logger.error(f"Error saving config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/config/not-allowed-sites", tags=["Config Admin"])
async def add_not_allowed_site(request: Request):
    """Add a site to not_allowed_sites."""
    try:
        body = await request.json()
        site = body.get("site", "").strip()
        if not site:
            raise HTTPException(status_code=400, detail="Site bo'sh bo'lishi mumkin emas")

        config = load_full_config()
        image_config = config.setdefault("image", {})
        sites = image_config.get("not_allowed_sites", [])
        if site not in sites:
            sites.append(site)
            image_config["not_allowed_sites"] = sites
            config["image"] = image_config
            save_full_config(config)
        return {"message": "Qo'shildi", "sites": sites}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding site: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/config/not-allowed-sites", tags=["Config Admin"])
async def delete_not_allowed_site(site: str):
    """Remove a site from not_allowed_sites."""
    try:
        config = load_full_config()
        image_config = config.get("image", {})
        sites = image_config.get("not_allowed_sites", [])
        if site in sites:
            sites = [s for s in sites if s != site]
            image_config["not_allowed_sites"] = sites
            config["image"] = image_config
            save_full_config(config)
        return {"message": "O'chirildi", "sites": sites}
    except Exception as e:
        logger.error(f"Error deleting site: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/mxik-data", tags=["MXIK Management"])
async def get_mxik_data():
    """Fetch MXIK data from Excel file as JSON without headers."""
    try:
        if not os.path.exists(EXCEL_FILE_PATH):
            raise HTTPException(status_code=404, detail="Excel file not found")

        # Read without header
        df = pd.read_excel(EXCEL_FILE_PATH, header=None, dtype=str)

        # Ensure we have at least 4 columns
        while len(df.columns) < 4:
            df[len(df.columns)] = ""

        # Map indices to names for the UI
        # Excel structure: Column 0 = ID, Column 1 = Name, Column 2 = mixk, Column 3 = package
        data = []
        for idx, row in df.iterrows():
            data.append(
                {
                    "row_id": idx,
                    "category_id": row[0] if 0 in row else "",
                    "name": row[1] if 1 in row else "",
                    "mxik_code": row[2] if 2 in row else "",
                    "package_code": row[3] if 3 in row else "",
                }
            )
        return data
    except Exception as e:
        logger.error(f"Error reading Excel: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/mxik-update", tags=["MXIK Management"])
async def update_mxik_data(request: Request):
    """Update rows in the MXIK Excel file without headers."""
    try:
        body = await request.json()
        updates = body.get("updates", [])

        if not os.path.exists(EXCEL_FILE_PATH):
            raise HTTPException(status_code=404, detail="Excel file not found")

        df = pd.read_excel(EXCEL_FILE_PATH, header=None, dtype=str)

        for update in updates:
            row_id_value = update.get("row_id")
            if row_id_value is None:
                continue
            try:
                row_id = int(row_id_value)
            except (ValueError, TypeError):
                continue
            if 0 <= row_id < len(df):
                if "category_id" in update:
                    df.iloc[row_id, 0] = str(update["category_id"])
                if "name" in update:
                    df.iloc[row_id, 1] = str(update["name"])
                if "mxik_code" in update:
                    df.iloc[row_id, 2] = str(update["mxik_code"])
                if "package_code" in update:
                    df.iloc[row_id, 3] = str(update["package_code"])

        df.to_excel(EXCEL_FILE_PATH, index=False, header=False)
        return {"message": "Dinamik ravishda saqlandi"}
    except Exception as e:
        logger.error(f"Error updating Excel: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/mxik-add", tags=["MXIK Management"])
async def add_mxik_item(request: Request):
    """Add a new row to the MXIK Excel file without headers."""
    try:
        body = await request.json()
        item = body.get("item", {})

        if not os.path.exists(EXCEL_FILE_PATH):
            raise HTTPException(status_code=404, detail="Excel file not found")

        df = pd.read_excel(EXCEL_FILE_PATH, header=None, dtype=str)

        # Construct new row list, handling None values properly
        def safe_str(value):
            """Convert value to string, handling None values."""
            return str(value) if value is not None else ""
        
        new_row = [
            safe_str(item.get("category_id")),
            safe_str(item.get("name")),
            safe_str(item.get("mxik_code")),
            safe_str(item.get("package_code")),
        ]

        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        df.to_excel(EXCEL_FILE_PATH, index=False, header=False)
        return {"message": "Yangi item muvaffaqiyatli qo'shildi"}
    except Exception as e:
        import traceback

        traceback.print_exc()
        logger.error(f"Error adding to Excel: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/mxik-delete/{row_id}", tags=["MXIK Management"])
async def delete_mxik_item(row_id: int):
    """Delete a row from the MXIK Excel file without headers."""
    try:
        if not os.path.exists(EXCEL_FILE_PATH):
            raise HTTPException(status_code=404, detail="Excel file not found")

        df = pd.read_excel(EXCEL_FILE_PATH, header=None, dtype=str)

        if 0 <= row_id < len(df):
            df = df.drop(df.index[row_id])
            df.to_excel(EXCEL_FILE_PATH, index=False, header=False)
            return {"message": "Item muvaffaqiyatli o'chirildi"}
        else:
            raise HTTPException(status_code=404, detail="Row not found")
    except Exception as e:
        logger.error(f"Error deleting from Excel: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/mxik-download", tags=["MXIK Management"])
async def download_mxik_excel():
    """Download the modified MXIK Excel file."""
    if not os.path.exists(EXCEL_FILE_PATH):
        raise HTTPException(status_code=404, detail="Excel file not found")

    return FileResponse(
        path=EXCEL_FILE_PATH,
        filename="mxik-codes-updated.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.post("/api/mxik-upload", tags=["MXIK Management"])
async def upload_mxik_excel(file: UploadFile = File(...)):
    """Upload and replace the MXIK Excel file with validation."""
    try:
        # Validate file extension
        if not file.filename.endswith((".xlsx", ".xls")):
            raise HTTPException(
                status_code=400,
                detail="Faqat Excel fayllar qabul qilinadi (.xlsx, .xls)"
            )

        # Read uploaded file
        contents = await file.read()
        
        try:
            df = pd.read_excel(BytesIO(contents), header=None, dtype=str)
        except Exception as e:
            logger.error(f"Error reading Excel file: {e}")
            raise HTTPException(
                status_code=400,
                detail="Excel faylni o'qib bo'lmadi"
            )

        # Validate column count - must have exactly 4 columns
        if len(df.columns) != 4:
            raise HTTPException(
                status_code=400,
                detail="Excel fayl aynan 4 ta ustunga ega bo'lishi kerak"
            )

        # Validate file is not empty
        if len(df) == 0:
            raise HTTPException(
                status_code=400,
                detail="Excel fayl bo'sh bo'lishi mumkin emas"
            )

        # Ensure directory exists
        directory = os.path.dirname(EXCEL_FILE_PATH)
        if directory:
            os.makedirs(directory, exist_ok=True)

        # Save to file
        try:
            df.to_excel(EXCEL_FILE_PATH, index=False, header=False)
        except Exception as e:
            logger.error(f"Error saving Excel file: {e}")
            raise HTTPException(
                status_code=500,
                detail="Faylni saqlashda xatolik yuz berdi"
            )

        return {
            "message": "Excel fayl muvaffaqiyatli yuklandi va almashtirildi",
            "filename": file.filename,
            "rows": len(df)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error uploading MXIK Excel: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Xatolik yuz berdi: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
