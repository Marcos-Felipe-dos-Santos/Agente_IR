"""
Configurações centrais da aplicação.
"""

from pathlib import Path

# ── Diretórios ──────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# ── Banco de dados ──────────────────────────────────────────────────
DATABASE_URL = f"sqlite:///{DATA_DIR / 'irpf.db'}"

# ── Aplicação ───────────────────────────────────────────────────────
APP_TITLE = "Agent IR — Automação Fiscal IRPF"
APP_VERSION = "0.1.0"
