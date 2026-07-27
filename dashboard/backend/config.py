import os
from ebaypricer.paths import DB_PATH, PROJECT_ROOT, DATA_DIR

DB_PATH_STR = str(DB_PATH)
LOG_PATH = os.path.join(PROJECT_ROOT, "logs", "main.log")
DATA_DIR_STR = str(DATA_DIR)
EXCEL_PATH = os.environ.get("EBAY_EXCEL_PATH", os.path.join("H:", os.sep, "My Drive", "ebay", "ebay_sold_orders.xlsx"))
