import os
import sqlite3
import subprocess
import threading
import time

import app
import job_manager
from job_manager import JobStatus


class QueueExecutor(threading.Thread):
    def __init__(self):
        super().__init__()
        self._stop_flag = threading.Event()

        # Initialize the queue table if needed
        with sqlite3.connect(app.SQLITE_DB_PATH) as conn:
            db = conn.cursor()
            db.execute("CREATE TABLE IF NOT EXISTS queue (job_id TEXT NOT NULL, timestamp INT NOT NULL)")
            conn.commit()

    def run(self):
        conn = sqlite3.connect(app.SQLITE_DB_PATH)
        db = conn.cursor()
        while not self._stop_flag.is_set():
            db.execute("SELECT job_id FROM queue ORDER BY timestamp LIMIT 1")
            rows = db.fetchall()
            if len(rows) > 0:
                # Check that there actually is a job in the queue

                job_id = rows[0][0]  # Only 1 row since we specified LIMIT 1

                rsa_key_size = job_manager.get_job(job_id).get_key_size()

                folder_path = os.path.join(app.JOBS_FOLDER_PATH, job_id)
                conf_path = os.path.join(folder_path, "{}.conf".format(job_id))
                key_path = os.path.join(folder_path, "{}.key".format(job_id))
                csr_path = os.path.join(folder_path, "{}.csr".format(job_id))

                cmd = "openssl req -new -newkey rsa:{} -nodes -keyout {} -out {} -config {}"\
                    .format(rsa_key_size, key_path, csr_path, conf_path)
                try:
                    # use check_output so that output isn't printed to console
                    subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT)

                    # Clear the error_message field in case it contains old message, set status to generated
                    job_manager.set_job_error_message(job_id, None)
                    job_manager.set_job_status(job_id, JobStatus.GENERATED)

                except subprocess.CalledProcessError as e:
                    # Error creating the CSR and key file
                    # Setting the job status and saving error message
                    job_manager.set_job_error_message(job_id, e.output.decode("utf-8"))
                    job_manager.set_job_status(job_id, JobStatus.ERROR)
                    print("Error code: {}  -  message: {}".format(e.returncode, e.output.decode("utf-8")))

                db.execute("DELETE FROM queue WHERE job_id = ?", (job_id,))
                conn.commit()

            else:
                # If queue was empty, sleep for 5 seconds and check again
                i = 0
                # Instead of sleeping 5 seconds, sleep 1 second 5 times so that we can stop quicker if the
                # stop flag is set, instead of having to wait the whole 5 seconds.
                while i < 5 and not self._stop_flag.is_set():
                    time.sleep(1)
                    i += 1

    def stop(self):
        self._stop_flag.set()

    @staticmethod
    def add_to_queue(job_id: str):
        with sqlite3.connect(app.SQLITE_DB_PATH) as conn:
            db = conn.cursor()
            timestamp = int(time.time())
            db.execute("INSERT INTO queue (job_id, timestamp) VALUES (?, ?)", (job_id, timestamp))
            conn.commit()
