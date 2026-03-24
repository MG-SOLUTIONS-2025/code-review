from fastapi import APIRouter, HTTPException, Query
from loguru import logger

from gateway.services.defectdojo import DefectDojoClient

router = APIRouter()


@router.get("/findings")
async def get_findings(
    limit: int = Query(20, ge=1, le=500),
    offset: int = Query(0, ge=0),
    severity: str | None = Query(
        None, pattern="^(Critical|High|Medium|Low|Info)$"
    ),
    scan_type: str | None = Query(None),
):
    try:
        async with DefectDojoClient() as client:
            return await client.get_findings(limit=limit, offset=offset, severity=severity, scan_type=scan_type)
    except Exception as e:
        logger.error("Failed to fetch findings from DefectDojo: {}", e)
        raise HTTPException(status_code=502, detail="Failed to fetch findings from DefectDojo")


@router.get("/findings/summary")
async def findings_summary():
    counts: dict[str, int] = {}
    total = 0
    offset = 0
    page_size = 500

    try:
        async with DefectDojoClient() as client:
            while True:
                page = await client.get_findings(limit=page_size, offset=offset)
                results = page.get("results", [])
                if not results:
                    break
                for f in results:
                    sev = f.get("severity", "Unknown")
                    counts[sev] = counts.get(sev, 0) + 1
                total = page.get("count", 0)
                offset += len(results)
                if offset >= total or len(results) < page_size:
                    break
    except Exception as e:
        logger.error("Failed to fetch findings summary from DefectDojo: {}", e)
        raise HTTPException(status_code=502, detail="Failed to fetch findings summary")

    return {"severity_counts": counts, "total": total}
