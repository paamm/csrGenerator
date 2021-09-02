from app import startup_tasks, stop_app

bind = "0.0.0.0:5000"
backlog = 1000

worker_class = "gevent"
workers = 5
timeout = 30
keepalive = 5


def on_starting(_):
    startup_tasks()


def on_exit(_):
    stop_app(None, None)
