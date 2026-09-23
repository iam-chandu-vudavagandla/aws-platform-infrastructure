from prometheus_client import multiprocess

bind = "0.0.0.0:8080"
workers = 2
threads = 2
timeout = 30

accesslog = "-"
errorlog = "-"


def child_exit(_server, worker):
    multiprocess.mark_process_dead(worker.pid)
