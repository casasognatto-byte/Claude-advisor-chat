"""Catálogo de cores de MDP/MDF das linhas que o Grupo Simonetto trabalha —
Simonetto e Stimmo. Importado de uma planilha .xlsx que o Davi mantém e
reenvia de tempos em tempos (painel do diretor tem o botão de reimportar).

A planilha real observada (`CORES DAS LINHAS.xlsx`) tem uma aba por ano
(2023, 2024, 2025...) com layout: linha de cabeçalho com o nome de cada marca
("SIMONETTO", "STIMMO"/"ESTIMMO") numa coluna, e abaixo dela pares
(nome da cor, fabricante da placa) até a lista acabar. Pegamos sempre a aba
mais recente (maior ano no nome) e localizamos as colunas pelo texto do
cabeçalho, não pela posição fixa — para tolerar pequenas mudanças de layout
entre uma planilha e outra.

Imports de `app.main` ficam dentro das funções para evitar import circular.
"""

import io
import re
import secrets

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

router = APIRouter(prefix="/api/materials")

# Aliases conhecidos pro nome de cada marca no cabeçalho da planilha —
# "ESTIMMO" apareceu como erro de digitação de "STIMMO" numa das abas.
BRAND_ALIASES = {
    "simonetto": "simonetto",
    "stimmo": "stimmo",
    "estimmo": "stimmo",
}
BRAND_LABELS = {"simonetto": "Simonetto", "stimmo": "Stimmo"}


def init_materials_db() -> None:
    from app.main import DB_ENABLED, _db

    if not DB_ENABLED:
        return
    try:
        with _db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS material_colors (
                    id           TEXT PRIMARY KEY,
                    brand        TEXT NOT NULL,
                    name         TEXT NOT NULL,
                    manufacturer TEXT,
                    imported_by  TEXT NOT NULL,
                    imported_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_material_colors_brand "
                "ON material_colors (brand, name);"
            )
    except Exception as e:
        print(f"[init_materials_db] falha: {e}")


def _parse_workbook(content: bytes) -> dict:
    """Devolve {"simonetto": [(nome, fabricante), ...], "stimmo": [...]}.
    Lança ValueError com mensagem clara se não achar nenhuma marca conhecida."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)

    # Prefere a aba com o maior ano no nome (planilha real tem uma aba por
    # ano); se nenhuma aba parecer um ano, usa a última (ordem de criação).
    year_sheets = [(int(m.group()), name) for name in wb.sheetnames if (m := re.search(r"\d{4}", name))]
    sheet_name = max(year_sheets)[1] if year_sheets else wb.sheetnames[-1]
    ws = wb[sheet_name]

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ValueError(f"Aba '{sheet_name}' está vazia.")
    header = rows[0]

    brand_cols: dict[str, int] = {}
    for col_idx, cell in enumerate(header):
        if not isinstance(cell, str):
            continue
        key = cell.strip().lower()
        if key in BRAND_ALIASES:
            brand_cols[BRAND_ALIASES[key]] = col_idx

    if not brand_cols:
        raise ValueError(
            f"Não encontrei nenhuma coluna 'SIMONETTO' ou 'STIMMO' no cabeçalho da aba '{sheet_name}'."
        )

    result: dict[str, list] = {brand: [] for brand in brand_cols}
    for row in rows[1:]:
        for brand, col_idx in brand_cols.items():
            if col_idx >= len(row):
                continue
            name = row[col_idx]
            if not isinstance(name, str) or not name.strip():
                continue
            manufacturer = None
            if col_idx + 1 < len(row) and isinstance(row[col_idx + 1], str) and row[col_idx + 1].strip():
                manufacturer = row[col_idx + 1].strip()
            result[brand].append((name.strip(), manufacturer))

    return result


@router.post("/import")
async def import_colors(request: Request, file: UploadFile = File(...)):
    """Substitui o catálogo inteiro pelo conteúdo da planilha enviada — só o
    diretor pode (mesma régua de outras ações administrativas)."""
    from app.main import _db, _require_db, require_admin

    user = require_admin(request)
    _require_db()
    content = await file.read()
    try:
        parsed = _parse_workbook(content)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"Não consegui ler a planilha: {e}")

    total = sum(len(v) for v in parsed.values())
    if not total:
        raise HTTPException(400, "Planilha lida, mas nenhuma cor encontrada nas colunas de marca.")

    with _db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM material_colors")
        for brand, colors in parsed.items():
            for name, manufacturer in colors:
                cur.execute(
                    "INSERT INTO material_colors (id, brand, name, manufacturer, imported_by) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    ("mc" + secrets.token_hex(8), brand, name, manufacturer, user["username"]),
                )

    return {"ok": True, "counts": {brand: len(colors) for brand, colors in parsed.items()}}


@router.get("/colors")
def list_colors(request: Request, brand: str | None = None):
    from app.main import DB_ENABLED, _db, require_user

    require_user(request)
    if not DB_ENABLED:
        return []
    with _db() as conn, conn.cursor() as cur:
        if brand:
            cur.execute(
                "SELECT id, brand, name, manufacturer FROM material_colors "
                "WHERE brand = %s ORDER BY name",
                (brand,),
            )
        else:
            cur.execute("SELECT id, brand, name, manufacturer FROM material_colors ORDER BY brand, name")
        rows = cur.fetchall()
    return [
        {"id": r[0], "brand": r[1], "brandLabel": BRAND_LABELS.get(r[1], r[1]), "name": r[2], "manufacturer": r[3]}
        for r in rows
    ]


@router.get("/status")
def import_status(request: Request):
    """Pro painel admin mostrar quando foi a última importação e quantas
    cores tem hoje, sem precisar listar tudo."""
    from app.main import DB_ENABLED, _db, require_admin

    require_admin(request)
    if not DB_ENABLED:
        return {"total": 0, "byBrand": {}, "lastImportedAt": None, "lastImportedBy": None}
    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT brand, COUNT(*) FROM material_colors GROUP BY brand")
        by_brand = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute(
            "SELECT imported_by, EXTRACT(EPOCH FROM imported_at) FROM material_colors "
            "ORDER BY imported_at DESC LIMIT 1"
        )
        last = cur.fetchone()
    return {
        "total": sum(by_brand.values()),
        "byBrand": by_brand,
        "lastImportedAt": float(last[1]) if last else None,
        "lastImportedBy": last[0] if last else None,
    }
