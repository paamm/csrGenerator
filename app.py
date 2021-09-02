import os
import shutil
import signal
import sqlite3
import sys
from typing import Optional

from flask import Flask

import job_manager
from job_manager import JobStatus
from queue_executor import QueueExecutor
from routes import route_app

# TODO List page, delete option in generate page

# Static variables
JOBS_FOLDER_PATH = os.getenv("CSR_JOBS", os.getcwd() + "/jobs/")
SQLITE_DB_PATH = os.path.join(os.getenv("CSR_DB", os.getcwd()), "sqlite.db")

# Set to none for scope, will get set in #startup_tasks
queue_thread: Optional[QueueExecutor] = None


def cleanup():
    """ Cleanup the database and jobs folder by removing invalid jobs
        If a job is in the database but some/all of its files are missing, remove from DB and delete files, if any
        If a job is in the jobs folder but not in the DB, don't delete the folder but log that we found a bad folder
        """

    print("Running cleanup operations.")
    with sqlite3.connect(SQLITE_DB_PATH) as conn:
        db = conn.cursor()
        # folder names to DB - No deletion
        folder_names = os.listdir(JOBS_FOLDER_PATH)
        for job_id in folder_names:
            # If folder is empty, delete it (since no data will be lost)
            folder_path = os.path.join(JOBS_FOLDER_PATH, job_id)
            if len(os.listdir(folder_path)) == 0:
                os.rmdir(folder_path)
                print("An empty folder named {} was found in the jobs folder and was deleted.".format(job_id))
                continue

            db.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,))
            rows = db.fetchall()
            if len(rows) == 0:
                # No jobs found in db with that id
                print("A folder named {} was found in the jobs folder, but no job with that id could be found in the "
                      "database.".format(job_id))

        # DB to folder - delete if missing file(s)
        db.execute("SELECT id,status FROM jobs")
        job_ids = db.fetchall()
        for job_id, status in job_ids:
            status = JobStatus(status)
            valid = True

            folder_path = os.path.join(JOBS_FOLDER_PATH, job_id)
            if not os.path.isdir(folder_path):
                valid = False

            conf_path = os.path.join(folder_path, "{}.conf".format(job_id))
            if not os.path.isfile(conf_path):
                valid = False

            if status == JobStatus.GENERATED:
                key_path = os.path.join(folder_path, "{}.key".format(job_id))
                if not os.path.isfile(key_path):
                    valid = False

                csr_path = os.path.join(folder_path, "{}.csr".format(job_id))
                if not os.path.isfile(csr_path):
                    valid = False

            if not valid:
                # Missing at least one file, delete from DB and remove folder if present
                db.execute("DELETE FROM jobs WHERE id=?", (job_id,))
                conn.commit()
                shutil.rmtree(folder_path, ignore_errors=True)  # Remove folder and sub-files
                print("Job {} removed from database due to missing files.".format(job_id))
    print("Completed cleanup operations.")


def stop_app(_, __):
    print("Stopping the app...")
    if queue_thread:  # Check if queue_thread exists, sigint could be received before thread is created
        queue_thread.stop()
    sys.exit(0)


def startup_tasks():
    # Create the database if it doesn't exist
    job_manager.initialize_db()

    # Start the queue executor thread
    global queue_thread
    queue_thread = QueueExecutor()
    queue_thread.start()

    # Run the cleanup ops
    cleanup()


def create_app():
    app = Flask(__name__)
    app.register_blueprint(route_app)  # Register the routes from the routes.py file

    if app.env == "development":
        # If app is in development, call startup_tasks manually as there is no gunicorn to call it for us
        startup_tasks()
        # Also register the SIGINT signal to stopping the queue thread (only needed when not running w/ gunicorn)
        signal.signal(signal.SIGINT, stop_app)

    return app


if __name__ == '__main__':
    app = create_app()
    app.run()
