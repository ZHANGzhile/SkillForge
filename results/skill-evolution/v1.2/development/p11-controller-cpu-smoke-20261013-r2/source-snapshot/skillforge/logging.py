import json
import logging


logger = logging.getLogger("skillforge")


def event(name, **fields):
    logger.info(json.dumps({"event": name, **fields}, ensure_ascii=False))
