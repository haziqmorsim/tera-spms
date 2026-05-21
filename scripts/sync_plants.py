from __future__ import annotations
from app.db.session import SessionLocal
from app.services.playwright_client import extract_plants_from_portal
from app.services.plant_sync import sync_plants_from_dom
from app.utils.job_logger import start_run, finish_run

JOB_NAME = "sync_plants"

def main():
    db = SessionLocal()
    run_id = None
    
    try:
        run_id = start_run(db, JOB_NAME)

        rows = extract_plants_from_portal(headless=False, interactive_login=True)
        sync_plants_from_dom(db, rows)

        finish_run(db, run_id, "success", f"Synced {len(rows)} plant rows.", {"rows": len(rows)},)
        print(f"Plant sync is complete. Total plants = {len(rows)}")
    
    except Exception as e:
        db.rollback()
        if run_id is not None:
            finish_run(db, run_id, "fail", str(e))
        raise

    finally:
        db.close()
    

if __name__ == "__main__":
    main()