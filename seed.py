import os
from app.core.database import SessionLocal
from app.models.entities import Contribuinte

def seed_db():
    cpf = os.getenv("SEED_CPF", "000.000.000-00")
    nome = os.getenv("SEED_NOME", "Usuário Local")
    db = SessionLocal()
    if not db.query(Contribuinte).filter(Contribuinte.id == 1).first():
        contrib = Contribuinte(id=1, nome_completo=nome, cpf=cpf)
        db.add(contrib)
        db.commit()
        print("✅ Contribuinte criado com sucesso!")
    else:
        print("✅ Contribuinte já existe no banco.")
    db.close()

if __name__ == "__main__":
    seed_db()