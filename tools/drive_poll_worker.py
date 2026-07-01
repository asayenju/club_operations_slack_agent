import logging
import time

from common.config import get_ingestion_settings
from ingestion_api.drive_sync import DriveSyncService


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    settings = get_ingestion_settings()
    interval = max(settings.drive_poll_interval_seconds, 30)
    service = DriveSyncService.from_settings()
    logger.info("Drive polling worker started with interval=%s seconds", interval)

    while True:
        try:
            result = service.poll_changes()
            logger.info(
                "Drive poll complete: changed=%s synced_folders=%s",
                result.changed_items,
                result.synced_folders,
            )
        except Exception:
            logger.exception("Drive poll failed")
        time.sleep(interval)


if __name__ == "__main__":
    main()
