FROM python:3

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV FLASK_APP=app.py
ENV CSR_JOBS="/csrgen/jobs"
ENV CSR_DB="/csrgen/"

#STOPSIGNAL SIGINT

EXPOSE 5000
ENTRYPOINT ["/app/entrypoint.sh"]
CMD exec gunicorn --log-level info --config gunicorn_config.py wsgi:app