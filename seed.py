import os
from app.core.database import SessionLocal
from app.models.entities import Contribuinte

def seed_db():
    db = SessionLocal()
    # CPF lido da variável de ambiente. Nunca deve estar hardcoded no código.
    # Defina SEED_CPF=000.123.456-00 no seu .env antes de executar.
    cpf_seguro = os.getenv("SEED_CPF", "000.000.000-00")
    if not db.query(Contribuinte).filter(Contribuinte.id == 1).first():
        usuario = Contribuinte(id=1, nome_completo="Usuario Padrao", cpf=cpf_seguro)
        db.add(usuario)
        db.commit()
        print("✅ Contribuinte Marcos (ID: 1) criado com sucesso!")
    else:
        print("✅ O utilizador já existe no banco.")
    db.close()

if __name__ == "__main__":
    seed_db()