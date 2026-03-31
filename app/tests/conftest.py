"""
Test fixtures: in-memory SQLite database for isolation
"""
import sys
from pathlib import Path
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Add app directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import Base


@pytest.fixture
def db_session():
    """Create a fresh in-memory database for each test (model tests only)"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def client():
    """FastAPI test client with in-memory database (thread-safe via StaticPool)"""
    from fastapi.testclient import TestClient
    from models import get_db, JournalCompliance
    from main import app

    # StaticPool reuses the same connection across threads
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(test_engine)
    TestSession = sessionmaker(bind=test_engine)

    def override_get_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    # Initialize compliance record
    init_session = TestSession()
    if not init_session.query(JournalCompliance).first():
        init_session.add(JournalCompliance())
        init_session.commit()
    init_session.close()

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    app.dependency_overrides.clear()
