import datetime
from app import create_app, seed_default_data
from repositories.db import db


def init_db():
    app = create_app()
    with app.app_context():
        db.create_all()
        print("Populating initial data...")
        seed_default_data()
        print("Initialization complete!")


if __name__ == '__main__':
    init_db()
