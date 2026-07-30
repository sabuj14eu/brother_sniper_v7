# gunicorn.conf.py — Brother Sniper Bot v4
# Run: gunicorn -c gunicorn.conf.py bot:app

bind         = "127.0.0.1:5000"
backlog      = 64
workers      = 1          # MUST be 1 — shared XTB socket + state
threads      = 4          # handles webhook + health + admin concurrently
worker_class = "gthread"
timeout      = 30
keepalive    = 5

loglevel        = "info"
accesslog       = "access.log"
errorlog        = "error.log"
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(D)sus'

proc_name            = "sniper-bot-v4"
limit_request_line   = 4094
limit_request_fields = 50

def post_worker_init(worker):
    worker.log.info("[GUNICORN] post_worker_init — running bot startup() in worker")
    from bot import startup
    startup()

def on_exit(server):
    server.log.info("[GUNICORN] on_exit — cleanup")
    try:
        from bot import xtb, _shutdown
        _shutdown.set()
        xtb.disconnect()
    except Exception as e:
        server.log.error(f"Cleanup error: {e}")

def worker_exit(server, worker):
    server.log.warning(f"[GUNICORN] Worker {worker.pid} exited unexpectedly")
