"""
db_utils.py — ScreenEdge Africa
Helper partagé : connexion PostgreSQL via SSH tunnel (paramiko natif).
Utilise le transport paramiko directement — compatible paramiko 5.x.
Utilisé par : agent_aml_pep.ipynb, gafi_monitor.py, apply_changes.py
"""

import os
import socket
import select
import threading
import warnings
from contextlib import contextmanager

import paramiko
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

warnings.filterwarnings("ignore")
load_dotenv(override=True)

SSH_HOST     = os.getenv("PG_SSH_HOST", "195.200.14.241")
SSH_USER     = os.getenv("PG_SSH_USER", "root")
SSH_PASSWORD = os.getenv("PG_SSH_PASSWORD")
PG_DATABASE  = os.getenv("PG_DATABASE", "compliance_db")
PG_USER      = os.getenv("PG_USER", "postgres")
PG_PASSWORD  = os.getenv("PG_PASSWORD")


# ── Tunnel SSH minimal (paramiko transport, sans sshtunnel) ───────────────────

class _TunnelHandler(threading.Thread):
    """Thread de relais bidirectionnel entre un socket local et un channel SSH."""
    def __init__(self, chan: paramiko.Channel, sock: socket.socket):
        super().__init__(daemon=True)
        self.chan = chan
        self.sock = sock

    def run(self):
        while True:
            r, _, x = select.select([self.chan, self.sock], [], [self.chan, self.sock], 5)
            if x:
                break
            if self.chan in r:
                data = self.chan.recv(4096)
                if not data:
                    break
                try:
                    self.sock.sendall(data)
                except OSError:
                    break
            if self.sock in r:
                data = self.sock.recv(4096)
                if not data:
                    break
                try:
                    self.chan.sendall(data)
                except OSError:
                    break
        try:
            self.chan.close()
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


@contextmanager
def _ssh_local_forward(remote_host: str = "127.0.0.1", remote_port: int = 5432):
    """
    Ouvre un tunnel SSH via paramiko transport et yield le port local.
    Usage :
        with _ssh_local_forward() as local_port:
            conn = psycopg2.connect(host='127.0.0.1', port=local_port, ...)
    """
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        SSH_HOST, port=22,
        username=SSH_USER, password=SSH_PASSWORD,
        timeout=15, allow_agent=False, look_for_keys=False,
    )
    transport = client.get_transport()
    transport.set_keepalive(10)

    # Socket serveur local sur un port libre
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    local_port = srv.getsockname()[1]
    srv.listen(10)

    def _accept_loop():
        while True:
            try:
                sock, addr = srv.accept()
            except OSError:
                break
            try:
                chan = transport.open_channel(
                    "direct-tcpip", (remote_host, remote_port), addr
                )
            except Exception:
                sock.close()
                continue
            _TunnelHandler(chan, sock).start()

    t = threading.Thread(target=_accept_loop, daemon=True)
    t.start()

    try:
        yield local_port
    finally:
        srv.close()
        client.close()


# ── Détection mode local (sur VPS) vs tunnel (depuis PC) ─────────────────────
# PG_LOCAL=true dans .env → connexion directe PostgreSQL (pas de tunnel SSH)
# Utile quand le code tourne sur le VPS lui-même
_PG_LOCAL = os.getenv("PG_LOCAL", "false").lower() == "true"


# ── API publique ───────────────────────────────────────────────────────────────

@contextmanager
def get_pg_conn():
    """
    Ouvre une connexion psycopg2.
    - PG_LOCAL=true  → connexion directe localhost:5432 (code tourne sur le VPS)
    - PG_LOCAL=false → tunnel SSH paramiko (code tourne en local)
    """
    if _PG_LOCAL:
        conn = psycopg2.connect(
            host="127.0.0.1",
            port=5432,
            database=PG_DATABASE,
            user=PG_USER,
            password=PG_PASSWORD,
            connect_timeout=10,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
        try:
            yield conn
        finally:
            if not conn.closed:
                conn.close()
    else:
        with _ssh_local_forward() as local_port:
            conn = psycopg2.connect(
                host="127.0.0.1",
                port=local_port,
                database=PG_DATABASE,
                user=PG_USER,
                password=PG_PASSWORD,
                connect_timeout=10,
                cursor_factory=psycopg2.extras.RealDictCursor,
            )
            try:
                yield conn
            finally:
                if not conn.closed:
                    conn.close()


def query_one(sql: str, params=None) -> dict | None:
    """Retourne la première ligne (dict) ou None."""
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None


def query_all(sql: str, params=None) -> list[dict]:
    """Retourne toutes les lignes (liste de dicts)."""
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


def execute(sql: str, params=None) -> None:
    """Exécute INSERT/UPDATE/DELETE avec commit."""
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
