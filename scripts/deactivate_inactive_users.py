from __future__ import annotations
from dotenv import load_dotenv
from app.db.session import SessionLocal
from app.services.user_activity_service import (
    INACTIVE_USER_DAYS, 
    INACTIVE_USER_EXCLUDE_ADMINS, 
    deactivate_inactive_users,
)
from app.utils.job_logger import start_run, finish_run

load_dotenv()

JOB_NAME="deactivate_inactive_users"

def main() -> None:
    db = SessionLocal()
    run_id = None

    try:
        run_id = start_run(db, JOB_NAME)

        deactivated_users = deactivate_inactive_users(
            db, 
            inactive_days=INACTIVE_USER_DAYS, 
            exclude_admins=INACTIVE_USER_EXCLUDE_ADMINS,
        )

        message = (
            f"Inactive users deactivated: {len(deactivated_users)}\n"
            f"Inactive days: {INACTIVE_USER_DAYS}\n"
        )

        finish_run(
            db, 
            run_id, 
            "success", 
            message, 
            {
                "deactivated_count": len(deactivated_users), 
                "inactive_days": INACTIVE_USER_DAYS, 
                "exclude_admins": INACTIVE_USER_EXCLUDE_ADMINS, 
                "deactivated_users": [
                    {
                        "id": str(user["id"]), 
                        "full_name": user["full_name"], 
                        "username": user["username"], 
                        "email": user["email"], 
                        "role": user["role"], 
                        "last_signin_at": str(user["last_signin_at"]) if user["last_signin_at"] else None, 
                        "deactivated_at": str(user["deactivated_at"]) if user["deactivated_at"] else None, 
                        "deactivation_reason": user["deactivation_reason"],
                    }
                    for user in deactivated_users
                ],
            },
        )

        print(message)

        if(deactivated_users):
            print("Deactivated users:")
            for user in deactivated_users:
                print(
                    f"- {user['full_name']} | {user['email']} | "
                    f"Last sign-in: {user['last_signin_at']}"
                )

    except Exception as exc:
        db.rollback()

        if run_id is not None:
            finish_run(db, run_id, "fail", str(exc))

        raise

    finally:
        db.close()

if __name__ == "__main__":
    main()