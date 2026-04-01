from app.core.database import SessionLocal
from app.models.entities import Contribuinte

def seed_db():
    db = SessionLocal()
    if not db.query(Contribuinte).filter(Contribuinte.id == 1).first():
        marcos = Contribuinte(id=1, nome="Usuario Padrao", cpf="000.000.000-00")
        db.add(marcos)
        db.commit()
        print("✅ Contribuinte Marcos (ID: 1) criado com sucesso!")
    else:
        print("✅ O utilizador já existe no banco.")
    db.close()

if __name__ == "__main__":
    seed_db()