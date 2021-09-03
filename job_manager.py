import os
import sqlite3
from enum import Enum
from random import SystemRandom
from typing import Optional, List

import app


class JobStatus(Enum):
    CREATED = 0
    QUEUED = 1
    GENERATED = 2
    ERROR = 3

    def __eq__(self, other):
        if type(other) is JobStatus:
            return self.value == other.value
        elif type(other) is int:
            return self.value == other
        return NotImplemented


class Job:
    def __init__(self, job_id: str, config_contents: str, key_size: int, status: JobStatus, error_message: str):
        self._job_id = job_id
        self._config_contents = config_contents
        self._key_size = key_size
        self._status = status
        self._error_message = error_message

    def get_id(self) -> str:
        return self._job_id

    def get_config_contents(self) -> str:
        return self._config_contents

    def get_key_size(self) -> int:
        return self._key_size

    def get_status(self) -> JobStatus:
        return self._status

    def get_error_message(self) -> str:
        return self._error_message


def initialize_db() -> None:
    with sqlite3.connect(app.SQLITE_DB_PATH) as conn:
        db = conn.cursor()
        db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY,"
                   "key_size INT NOT NULL,"
                   "status INT NOT NULL DEFAULT 0,"
                   "error_message TEXT)")
        conn.commit()


def create_job(config_contents: str, key_size: int) -> str:
    def generate_random_id():
        alphabet = list("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890")  # length: 62
        crypto = SystemRandom()

        x = ""
        for i in range(10):
            x += alphabet[crypto.randrange(62)]
        return x

    with sqlite3.connect(app.SQLITE_DB_PATH) as conn:
        db = conn.cursor()
        rand_id = generate_random_id()

        while True:
            try:
                db.execute("INSERT INTO jobs (id, key_size, status) VALUES (?, ?, ?)",
                           (rand_id, key_size, JobStatus.CREATED.value))
            except sqlite3.IntegrityError:
                # If there is an IntegrityError, the random id is already in use, generate another one
                rand_id = generate_random_id()
                continue

            conn.commit()
            break

        folder_path = os.path.join(app.JOBS_FOLDER_PATH, rand_id)
        os.makedirs(folder_path)

        config_path = os.path.join(folder_path, "{}.conf".format(rand_id))
        with open(config_path, "w") as f_config:
            f_config.write(config_contents)
            f_config.close()
        return rand_id


def _get_job(job_id: str):
    """
    Returns the job in a tuple format.

    :param job_id: The id of the job to get
    :raises ValueError: Raised if no job can be found with the specified id
    :return: A tuple containing the id, the RSA key size, the status of the job and an error message obtain when
    generating the files (can be null)
    """
    with sqlite3.connect(app.SQLITE_DB_PATH) as conn:
        db = conn.cursor()
        db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        rows = db.fetchall()

        if len(rows) == 0:
            # No job with that ID
            raise ValueError("No job found with that ID.")

        # Since id is a unique field, there should only be one row
        return rows[0]


def get_job(job_id: str) -> Job:
    """
    Retrieves a job's information from the database.

    :param job_id: The id of the job to retrieve.
    :raises ValueError: Raised if no job can be found with the specified id
    :raises FileNotFoundError: Raised if the config file couldn't be read
    :return: A Job object
    """
    job = _get_job(job_id)
    rsa_key_size = job[1]
    status = JobStatus(job[2])
    error_message = job[3]

    # /%some_path%/job_id/job_id.conf
    conf_path = os.path.join(app.JOBS_FOLDER_PATH, job_id, "{}.conf".format(job_id))

    try:
        with open(conf_path, "r") as f:
            return Job(job_id, f.read(), rsa_key_size, status, error_message)
    except FileNotFoundError:
        raise FileNotFoundError("Could not open the config file for this job.")


def get_jobs() -> List[Job]:
    """
    Retrieves all the jobs currently in the database.

    :return: A list containing Job objects
    """

    with sqlite3.connect(app.SQLITE_DB_PATH) as conn:
        db = conn.cursor()
        db.execute("SELECT id FROM jobs")
        job_ids = db.fetchall()
        result: List[Optional[Job]] = [None] * len(job_ids)
        for i in range(len(job_ids)):
            result[i] = get_job(job_ids[i][0])
        return result


def set_job_status(job_id: str, status: JobStatus):
    with sqlite3.connect(app.SQLITE_DB_PATH) as conn:
        db = conn.cursor()
        # No need to catch error since query will not throw any, will just not do anything if id doesn't exist
        db.execute("UPDATE jobs SET status=? WHERE id=?", (status.value, job_id))
        conn.commit()


def set_job_error_message(job_id: str, error_message: Optional[str]):
    with sqlite3.connect(app.SQLITE_DB_PATH) as conn:
        db = conn.cursor()
        if error_message is None:
            # No error message, provided, clear error_message column (set to NULL)
            db.execute("UPDATE jobs SET error_message=NULL WHERE id=?", (job_id,))
        else:
            db.execute("UPDATE jobs SET error_message=? WHERE id=?", (error_message, job_id))
        conn.commit()
