# src/config/config.py
import os


class Config:
    DEBUG = os.getenv('DEBUG', '') == '1'
    SECRET_KEY = os.getenv('SECRET_KEY', 'default_secret_key')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///db.sqlite')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
