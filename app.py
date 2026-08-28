from __future__ import annotations

import os
import sys
import threading
import webbrowser
from pathlib import Path

from incandescence.async_runtime import AsyncRuntime
from incandescence.auth import AdminAuth
from incandescence.config import ConfigStore, runtime_paths, server_address
from incandescence.database import Database
from incandescence.media import MediaStore
from incandescence.member_auth import MemberAuth
from incandescence.notifications import BarkNotifier
from incandescence.scraper import FreeXScraper
from incandescence.share_auth import ShareAuth
from incandescence.sync_service import Scheduler, SyncService
from incandescence.web import Application, create_server


def main() -> None:
    project_root = Path(__file__).resolve().parent
    data_dir, public_dir = runtime_paths(project_root)
    host, port = server_address()
    config = ConfigStore(data_dir)
    admin_auth = AdminAuth(data_dir)
    database = Database(data_dir / "reader.db")
    member_auth = MemberAuth(database)
    share_auth = ShareAuth(database)
    scraper = FreeXScraper(
        data_dir / "scraper-sessions.db", proxy_url_getter=config.proxy_url
    )
    scraper_runtime = AsyncRuntime()
    media = MediaStore(data_dir, database, proxy_url_getter=config.proxy_url)
    notifier = BarkNotifier(config)
    sync_service = SyncService(
        database, config, scraper, media, scraper_runtime, notifier=notifier
    )
    scheduler = Scheduler(config, sync_service)
    application = Application(
        data_dir=data_dir,
        public_dir=public_dir,
        database=database,
        config=config,
        admin_auth=admin_auth,
        member_auth=member_auth,
        share_auth=share_auth,
        notifier=notifier,
        scraper=scraper,
        sync_service=sync_service,
        scheduler=scheduler,
        scraper_runtime=scraper_runtime,
    )
    server = create_server((host, port), application)
    scheduler.start()
    shown_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{shown_host}:{server.server_address[1]}"
    print(f"X拾光 XGlow 本地阅读器已启动：{url}")
    print(f"数据目录：{data_dir}")
    if os.environ.get("NO_BROWSER") != "1" and sys.stdout.isatty():
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\n正在停止…")
    finally:
        scheduler.stop()
        server.server_close()
        scraper_runtime.stop()


if __name__ == "__main__":
    main()
