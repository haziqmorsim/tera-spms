from dotenv import load_dotenv
load_dotenv()

from app.db.session import SessionLocal
from app.services.playwright_client import extract_plants_from_portal, extract_inverters_global
from app.services.plant_sync import sync_plants_from_dom
from app.services.inverter_sync import upsert_inverters_global

def main():
    # Plants
    plant_rows = extract_plants_from_portal()
    db = SessionLocal()
    sync_plants_from_dom(db, plant_rows)
    db.close()

    # Inverters
    inv_rows = extract_inverters_global()
    db = SessionLocal()
    upsert_inverters_global(db, inv_rows)
    db.close()

    print("Daily sync is completed.")

if __name__ == "__main__":
    main()