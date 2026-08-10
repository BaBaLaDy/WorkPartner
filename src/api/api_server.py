"""Start FastAPI server only (for use alongside a separate Vite dev server).

Usage:
    conda run -n workpartner python -m src.api.api_server
"""

import logging
import sys

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s')
logger = logging.getLogger('api')


def main():
    from src.api.server import run_api_server
    from src.core.engine import WorkPartnerEngine

    logger.info("Creating WorkPartnerEngine...")
    engine = WorkPartnerEngine()
    logger.info("Engine created. Starting API server on http://127.0.0.1:8000")
    run_api_server(engine, host='127.0.0.1', port=8000, dev_mode=True)


if __name__ == '__main__':
    main()
