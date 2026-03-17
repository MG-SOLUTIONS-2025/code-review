from fastapi import APIRouter, Query

from gateway.services.defectdojo import DefectDojoClient

router = APIRouter()


@router.get("/findings")
async def get_findings(
    limit: int = Query(20),
    offset: int = Query(0),
    severity: str | None = Query(None),
):
    async with DefectDojoClient() as client:
        return await client.get_findings(limit=limit, offset=offset, severity=severity)


@router.get("/findings/summary")
async def findings_summary():
    async with DefectDojoClient() as client:
        findings = await client.get_findings(limit=1000, offset=0)
    counts: dict[str, int] = {}
    for f in findings.get("results", []):
        sev = f.get("severity", "Unknown")
        counts[sev] = counts.get(sev, 0) + 1
    return {"severity_counts": counts, "total": findings.get("count", 0)}
