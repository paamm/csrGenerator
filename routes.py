import os
import re
import textwrap

from flask import Blueprint, request, render_template, redirect

import app
import job_manager
from job_manager import JobStatus
from queue_executor import QueueExecutor

route_app = Blueprint('route_app', __name__)


@route_app.route('/', methods=["GET"])
def get_form():
    """ This route shows a form to create a new job """

    return render_template("index.html")


@route_app.route('/form', methods=["POST"])
def form_route():
    """ This route receives the form data from the index page, checks if there are any errors
        and creates the job if everything is valid. Redirects the user to /job/{job_id} """

    # Validate all the required fields
    if "rsa_key_size" not in request.form:
        return "An RSA key size must be specified.", 400
    rsa_key_size = request.form['rsa_key_size']
    if rsa_key_size not in ['2048', '4096']:
        return "Wrong RSA key size option.", 400
    rsa_key_size = int(rsa_key_size)

    if "country" not in request.form:
        return "A country must be specified.", 400
    country = request.form["country"].strip()
    if not country:
        return "A country must be specified.", 400

    if "state" not in request.form:
        return "A state must be specified.", 400
    state = request.form["state"].strip()
    if not state:
        return "A state must be specified.", 400

    if "city" not in request.form:
        return "A city must be specified.", 400
    city = request.form["city"].strip()
    if not city:
        return "A city must be specified.", 400

    if "organization" not in request.form:
        return "An organization must be specified.", 400
    organization = request.form["organization"].strip()
    if not organization:
        return "A organization must be specified.", 400

    if "fqdn" not in request.form:
        return "An FQDN must be specified.", 400
    fqdn = request.form["fqdn"].strip()
    if not fqdn:
        return "An FQDN must be specified.", 400

    # Optional values
    organizational_unit = request.form.get("OU", "").strip()

    email = request.form.get("email", "").strip()
    if email != "" and not re.fullmatch(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", email):
        return "A valid email must be provided", 400  # Very simple regex to validate string somewhat looks like email.

    raw_sans = request.form.get("san", "").strip()
    san_list = []
    if raw_sans != "":
        san_list = [s.strip() for s in raw_sans.split(",") if s.strip()]  # Add non-empty stripped strings
        san_list = list(set(san_list))  # Remove the duplicates

    if fqdn not in san_list:
        san_list = [fqdn] + san_list  # Prepend the fqdn if it is not already in the list

    config_file_contents = """\
    distinguished_name = req_distinguished_name
    req_extensions = req_ext
    prompt=no
    [req_distinguished_name]
    C = {}
    ST = {}
    L = {}
    O = {}""".format(country, state, city, organization)

    if organizational_unit:
        config_file_contents += "\nOU = " + organizational_unit

    if email:
        config_file_contents += "\nemailAddress = " + email

    config_file_contents += '''
    CN = {}
    [req_ext]
    subjectAltName = @alt_names
    [alt_names]'''.format(fqdn)
    config_file_contents = textwrap.dedent(config_file_contents)  # Dedent to allow the use of multiline string

    for i in range(len(san_list)):
        config_file_contents += "\nDNS.{} = {}".format(i + 1, san_list[i])

    job_id = job_manager.create_job(config_file_contents, rsa_key_size)

    return redirect("/job/{}".format(job_id))


@route_app.route("/job/<job_id>", methods=["GET"])
def job_info(job_id):
    """ This route shows the contents of the OpenSSL config file. User can change the contents of the file and save
        the changes or decide to generate the job """

    try:
        job = job_manager.get_job(job_id)
        conf_content = job.get_config_contents()
    except (ValueError, FileNotFoundError) as e:
        return str(e), 404

    conf_file_lines = len(conf_content.split("\n"))
    return render_template("job_info.html", job_id=job_id, conf_file_lines=conf_file_lines)


@route_app.route("/job/<job_id>", methods=["POST"])
def job_update(job_id):
    """ This route receives the new contents of the config file and tries to save it to disk.
        Redirects to /job/{job_id} """

    if "confFile" not in request.form:
        return "The contents of the config file must be specified.", 400

    conf_path = os.path.join(app.JOBS_FOLDER_PATH, job_id, "{}.conf".format(job_id))

    with open(conf_path, "w", newline='\n') as f:
        f.write(request.form['confFile'])

    return redirect("/job/{}".format(job_id))


@route_app.route("/job/<job_id>/generate", methods=["GET"])
def job_generation_info(job_id):
    """ If the job isn't generated, this route offers the user to generate the job by adding it to the queue.
        If this job is in the queue, it says so to the user.
        If this job had an error during the generation, it displays the error message to the user.
        If this job successfully generated, it shows the key file and csr file to the user """

    try:
        job = job_manager.get_job(job_id)
        status = job.get_status()
    except (ValueError, FileNotFoundError) as e:
        return str(e), 404

    if status == JobStatus.CREATED:
        # Job only created, not generated
        return render_template("job_not_generated.html", job_id=job_id)
    elif status == JobStatus.QUEUED:
        # Job already in queue
        return "The job is in the queue, please wait."
    elif status == JobStatus.GENERATED:
        # Job is generated, show results
        return render_template("job_generated.html", job_id=job_id)
    elif status == JobStatus.ERROR:
        split_error = job.get_error_message().split("\r\n")
        return render_template("job_error.html", job_id=job_id, split_error=split_error)


@route_app.route("/job/<job_id>/generate", methods=["POST"])
def job_generate(job_id):
    """ This route adds the job to the generation queue """

    try:
        _ = job_manager.get_job(job_id)
    except (ValueError, FileNotFoundError) as e:
        return str(e), 404

    job_manager.set_job_status(job_id, JobStatus.QUEUED)
    QueueExecutor.add_to_queue(job_id)
    return redirect(request.path)


@route_app.route("/job/<job_id>/key", methods=["GET"])
def job_get_key(job_id):
    """ This route returns the value of the SSL key for a generated job """

    try:
        job = job_manager.get_job(job_id)
    except (ValueError, FileNotFoundError) as e:
        return str(e), 404

    # Job exists, check that it has been generated
    if job.get_status() != JobStatus.GENERATED:
        return "Job hasn't generated yet", 404

    # Get key file
    # %jobs_path%/job_id/job_id.key
    key_path = os.path.join(app.JOBS_FOLDER_PATH, job_id, "{}.key".format(job_id))
    try:
        with open(key_path, "r") as f:
            return f.read()
    except FileNotFoundError:
        return "Couldn't open the key file, perhaps it hasn't properly generated.", 404


@route_app.route("/job/<job_id>/csr", methods=["GET"])
def job_get_csr(job_id):
    """ This route returns the value of the SSL CSR file for a generated job """

    try:
        job = job_manager.get_job(job_id)
    except (ValueError, FileNotFoundError) as e:
        return str(e), 404

    # Job exists, check that it has been generated
    if job.get_status() != JobStatus.GENERATED:
        return "Job hasn't generated yet", 404

    # Get csr file
    # %jobs_path%/job_id/job_id.csr
    csr_path = os.path.join(app.JOBS_FOLDER_PATH, job_id, "{}.csr".format(job_id))

    try:
        with open(csr_path, "r") as f:
            return f.read()
    except FileNotFoundError:
        return "Couldn't open the csr file, perhaps it hasn't properly generated.", 404


@route_app.route("/job/<job_id>/config", methods=["GET"])
def job_get_config(job_id):
    """ This route returns the contents of the config file for an existing job """

    try:
        job = job_manager.get_job(job_id)
    except (ValueError, FileNotFoundError) as e:
        return str(e), 404

    # Job exists
    return job.get_config_contents()
