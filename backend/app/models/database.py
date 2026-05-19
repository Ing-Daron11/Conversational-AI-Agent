"""
database.py — Modelos SQLAlchemy y sesión de base de datos

CONCEPTO — ¿Por qué PostgreSQL además de Redis?
  Redis es volátil: cuando el TTL expira (30 min sin actividad),
  la sesión desaparece. PostgreSQL es el almacenamiento PERSISTENTE:
  guarda el historial completo para siempre.

  Casos de uso de la BD relacional:
    - Ver historial completo de un usuario desde el Panel Admin (FASE 6)
    - Analizar patrones de uso (métricas, dashboard)
    - Recuperar contexto de sesiones anteriores si se implementa
      memoria a largo plazo en el futuro

MODELOS:
  User               → un registro por número de WhatsApp
  ConversationMessage → cada mensaje individual de cada conversación

PATRÓN ORM (Object-Relational Mapping):
  En lugar de escribir SQL crudo, SQLAlchemy nos permite trabajar con
  clases Python. La tabla "users" en la BD se mapea a la clase User.
  SQLAlchemy traduce User(...) a INSERT INTO users VALUES (...).
"""

from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, create_engine
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, Session
from contextlib import contextmanager

from app.config import get_settings

Base = declarative_base()


# ---- Modelos ----

class User(Base):
    """
    Representa un usuario del sistema, identificado por su número de WhatsApp.
    Un usuario puede tener muchos mensajes de conversación (relación 1:N).
    """
    __tablename__ = "users"

    id           = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String(30), unique=True, index=True, nullable=False)
    created_at   = Column(DateTime, default=datetime.utcnow)

    # Relación bidireccional: user.messages → lista de ConversationMessage
    messages = relationship(
        "ConversationMessage",
        back_populates="user",
        cascade="all, delete-orphan",  # si se borra el user, se borran sus mensajes
    )

    def __repr__(self):
        return f"<User phone={self.phone_number}>"


class ConversationMessage(Base):
    """
    Representa un mensaje individual en la conversación.
    role: "user" (mensaje del usuario) o "assistant" (respuesta del LLM).
    """
    __tablename__ = "conversation_messages"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    role       = Column(String(10), nullable=False)   # "user" | "assistant"
    content    = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="messages")

    def __repr__(self):
        return f"<Message role={self.role} user_id={self.user_id}>"


# ---- Conexión y sesión ----

def get_engine():
    """
    Crea el motor SQLAlchemy con pool_pre_ping=True.
    pool_pre_ping: antes de usar una conexión del pool, verifica que
    sigue viva (evita errores 'connection closed' después de inactividad).
    """
    settings = get_settings()
    return create_engine(settings.database_url, pool_pre_ping=True)


def init_db() -> None:
    """
    Crea todas las tablas en PostgreSQL si no existen.
    Equivalente a ejecutar CREATE TABLE IF NOT EXISTS para cada modelo.
    Se llama una vez al arrancar la app (ver main.py startup event).
    """
    engine = get_engine()
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_db_session():
    """
    Context manager para sesiones de BD con commit/rollback automático.
    Uso:
        with get_db_session() as db:
            db.add(User(...))
    """
    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine)
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---- Función de persistencia ----

def save_conversation_to_db(phone: str, history: list[dict]) -> None:
    """
    Persiste el historial completo de una sesión en PostgreSQL.

    Se llama como BackgroundTask en el webhook: no bloquea la respuesta
    al usuario, se ejecuta después de enviar el TwiML.

    Si el usuario ya existe, solo agrega los mensajes nuevos.
    Si es la primera vez, crea el registro de User primero.
    """
    clean_phone = phone.replace("whatsapp:", "").strip()

    with get_db_session() as db:
        # Buscar o crear el usuario
        user = db.query(User).filter_by(phone_number=clean_phone).first()
        if not user:
            user = User(phone_number=clean_phone)
            db.add(user)
            db.flush()   # obtiene el id antes del commit

        # Guardar cada mensaje del historial
        for msg in history:
            db.add(ConversationMessage(
                user_id=user.id,
                role=msg["role"],
                content=msg["content"],
            ))

