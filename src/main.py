import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.api.main import app

if __name__ == "__main__":
    import uvicorn
    from src.core.config import get_settings
    
    settings = get_settings()
    uvicorn.run(app, host=settings.host, port=settings.port)
