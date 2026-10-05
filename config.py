import os


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'eco-sphere-dev-secret-key-2026-strong-enough'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///ecosphere.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
