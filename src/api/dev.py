"""Start FastAPI server for local development.

Usage:
    conda run -n workpartner python -m src.api.dev
    conda run -n workpartner python -m src.api.dev --with-bridge

This launches:
- FastAPI on 127.0.0.1:8000 (with CORS for localhost:5173)
- Optionally: IM bridge (Telegram, Feishu) when --with-bridge is passed

Frontend (Vite) must be started separately:
    cd src/frontend/web && npm run dev
"""

import argparse
import logging
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s')
logger = logging.getLogger('dev')


def main():
    parser = argparse.ArgumentParser(description="WorkPartner dev server")
    parser.add_argument(
        '--with-bridge', '-b', action='store_true',
        help='Start IM bridge alongside the dev server (Telegram, Feishu, etc.)',
    )
    args = parser.parse_args()

    from src.core.engine import WorkPartnerEngine
    engine = WorkPartnerEngine()
    engine.run_serve(
        with_api=True, host='127.0.0.1', port=8000,
        dev_mode=True, on_shutdown=None,
        with_bridge=args.with_bridge,
    )


if __name__ == '__main__':
    main()
