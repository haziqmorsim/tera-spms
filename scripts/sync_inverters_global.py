from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text
from app.db.session import SessionLocal
from app.services.playwright_client import extract_inverters_global
from app.services.inverter_sync import upsert_inverters_global
from app.utils.job_logger import start_run, finish_run

JOB_NAME = "sync_inverters_global"

def main():
    db = SessionLocal()
    run_id = None
    
    try:
        run_id = start_run(db, JOB_NAME)

        rows = extract_inverters_global(headless=False, interactive_login=True)
        upsert_inverters_global(db, rows)

        finish_run(db, run_id, "success", f"Synced {len(rows)} inverter rows.", {"rows": len(rows)},)
        print(f"Inverter sync is complete. Total inverters = {len(rows)}")

    except Exception as e:
        db.rollback()
        if run_id is not None:
            finish_run(db, run_id, "fail", str(e))
        raise

    finally:
        db.close()

if __name__ == "__main__":
    main()
