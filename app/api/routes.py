"""
Rotas da API — endpoints CRUD para todas as entidades fiscais.
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.entities import (
    AtivoCripto,
    ContaBancaria,
    Contribuinte,
    OperacaoB3,
    Provento,
)
from app.schemas.fiscal import (
    AtivoCriptoCreate,
    AtivoCriptoRead,
    ContaBancariaCreate,
    ContaBancariaRead,
    ContribuinteCreate,
    ContribuinteRead,
    ContribuinteUpdate,
    OperacaoB3Create,
    OperacaoB3Read,
    ProventoCreate,
    ProventoRead,
)

router = APIRouter()


# ── helpers ─────────────────────────────────────────────────────────
def _get_or_404(db: Session, model, record_id: int):
    obj = db.get(model, record_id)
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{model.__name__} id={record_id} não encontrado.",
        )
    return obj


# ═══════════════════════════════════════════════════════════════════
#  Contribuinte
# ═══════════════════════════════════════════════════════════════════
@router.post(
    "/contribuintes",
    response_model=ContribuinteRead,
    status_code=status.HTTP_201_CREATED,
    tags=["Contribuinte"],
)
def criar_contribuinte(payload: ContribuinteCreate, db: Session = Depends(get_db)):
    obj = Contribuinte(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get(
    "/contribuintes",
    response_model=list[ContribuinteRead],
    tags=["Contribuinte"],
)
def listar_contribuintes(db: Session = Depends(get_db)):
    return list(db.scalars(select(Contribuinte)).all())


@router.get(
    "/contribuintes/{contribuinte_id}",
    response_model=ContribuinteRead,
    tags=["Contribuinte"],
)
def obter_contribuinte(contribuinte_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, Contribuinte, contribuinte_id)


@router.patch(
    "/contribuintes/{contribuinte_id}",
    response_model=ContribuinteRead,
    tags=["Contribuinte"],
)
def atualizar_contribuinte(
    contribuinte_id: int,
    payload: ContribuinteUpdate,
    db: Session = Depends(get_db),
):
    obj = _get_or_404(db, Contribuinte, contribuinte_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete(
    "/contribuintes/{contribuinte_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Contribuinte"],
)
def deletar_contribuinte(contribuinte_id: int, db: Session = Depends(get_db)):
    obj = _get_or_404(db, Contribuinte, contribuinte_id)
    db.delete(obj)
    db.commit()


# ═══════════════════════════════════════════════════════════════════
#  Conta Bancária
# ═══════════════════════════════════════════════════════════════════
@router.post(
    "/contas-bancarias",
    response_model=ContaBancariaRead,
    status_code=status.HTTP_201_CREATED,
    tags=["Conta Bancária"],
)
def criar_conta_bancaria(payload: ContaBancariaCreate, db: Session = Depends(get_db)):
    _get_or_404(db, Contribuinte, payload.contribuinte_id)
    obj = ContaBancaria(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get(
    "/contas-bancarias",
    response_model=list[ContaBancariaRead],
    tags=["Conta Bancária"],
)
def listar_contas_bancarias(
    contribuinte_id: int | None = None, db: Session = Depends(get_db)
):
    stmt = select(ContaBancaria)
    if contribuinte_id is not None:
        stmt = stmt.where(ContaBancaria.contribuinte_id == contribuinte_id)
    return list(db.scalars(stmt).all())


# ═══════════════════════════════════════════════════════════════════
#  Operações B3
# ═══════════════════════════════════════════════════════════════════
@router.post(
    "/operacoes-b3",
    response_model=OperacaoB3Read,
    status_code=status.HTTP_201_CREATED,
    tags=["Operações B3"],
)
def criar_operacao_b3(payload: OperacaoB3Create, db: Session = Depends(get_db)):
    _get_or_404(db, Contribuinte, payload.contribuinte_id)
    obj = OperacaoB3(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get(
    "/operacoes-b3",
    response_model=list[OperacaoB3Read],
    tags=["Operações B3"],
)
def listar_operacoes_b3(
    contribuinte_id: int | None = None, db: Session = Depends(get_db)
):
    stmt = select(OperacaoB3)
    if contribuinte_id is not None:
        stmt = stmt.where(OperacaoB3.contribuinte_id == contribuinte_id)
    return list(db.scalars(stmt).all())


# ═══════════════════════════════════════════════════════════════════
#  Ativos Cripto
# ═══════════════════════════════════════════════════════════════════
@router.post(
    "/ativos-cripto",
    response_model=AtivoCriptoRead,
    status_code=status.HTTP_201_CREATED,
    tags=["Ativos Cripto"],
)
def criar_ativo_cripto(payload: AtivoCriptoCreate, db: Session = Depends(get_db)):
    _get_or_404(db, Contribuinte, payload.contribuinte_id)
    obj = AtivoCripto(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get(
    "/ativos-cripto",
    response_model=list[AtivoCriptoRead],
    tags=["Ativos Cripto"],
)
def listar_ativos_cripto(
    contribuinte_id: int | None = None, db: Session = Depends(get_db)
):
    stmt = select(AtivoCripto)
    if contribuinte_id is not None:
        stmt = stmt.where(AtivoCripto.contribuinte_id == contribuinte_id)
    return list(db.scalars(stmt).all())


# ═══════════════════════════════════════════════════════════════════
#  Proventos
# ═══════════════════════════════════════════════════════════════════
@router.post(
    "/proventos",
    response_model=ProventoRead,
    status_code=status.HTTP_201_CREATED,
    tags=["Proventos"],
)
def criar_provento(payload: ProventoCreate, db: Session = Depends(get_db)):
    _get_or_404(db, Contribuinte, payload.contribuinte_id)
    obj = Provento(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get(
    "/proventos",
    response_model=list[ProventoRead],
    tags=["Proventos"],
)
def listar_proventos(
    contribuinte_id: int | None = None, db: Session = Depends(get_db)
):
    stmt = select(Provento)
    if contribuinte_id is not None:
        stmt = stmt.where(Provento.contribuinte_id == contribuinte_id)
    return list(db.scalars(stmt).all())
