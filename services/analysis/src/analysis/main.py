from fastapi import FastAPI
from analysis.config import settings

app = FastAPI(title=settings.SERVICE_NAME)

# This service is a READER. It queries Core Data Service via gRPC. 
# It NEVER accesses the database directly.

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/api/v1/analysis/correlation")
async def get_correlation():
    # Placeholder endpoint for correlation analysis
    # Will query Core Data Service via gRPC
    return {"message": "Correlation analysis results."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
