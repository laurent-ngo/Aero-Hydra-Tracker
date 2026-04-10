import pytest
import os
from unittest.mock import patch, MagicMock
from loadCSV import get_db_session


def test_uses_default_env_values():
    with patch.dict(os.environ, {
        'DB_PASSWORD': 'secret',
        'DB_HOST': 'localhost'
    }, clear=True), \
    patch('loadCSV.create_engine') as mock_engine, \
    patch('loadCSV.sessionmaker') as mock_sessionmaker:

        mock_session = MagicMock()
        mock_sessionmaker.return_value.return_value = mock_session

        session = get_db_session()

        call_url = mock_engine.call_args[0][0]
        assert 'neondb_owner' in call_url
        assert 'neondb' in call_url
        assert 'sslmode=disable' in call_url
        assert session == mock_session


def test_uses_custom_env_values():
    with patch.dict(os.environ, {
        'DB_USER':     'myuser',
        'DB_PASSWORD': 'mypass',
        'DB_HOST':     'myhost',
        'DB_NAME':     'mydb',
        'DB_OPTIONS':  'sslmode=require'
    }), \
    patch('loadCSV.create_engine') as mock_engine, \
    patch('loadCSV.sessionmaker'):

        get_db_session()

        call_url = mock_engine.call_args[0][0]
        assert 'myuser' in call_url
        assert 'mypass' in call_url
        assert 'myhost' in call_url
        assert 'mydb' in call_url
        assert 'sslmode=require' in call_url


def test_returns_session():
    with patch.dict(os.environ, {
        'DB_PASSWORD': 'secret',
        'DB_HOST':     'localhost'
    }, clear=True), \
    patch('loadCSV.create_engine'), \
    patch('loadCSV.sessionmaker') as mock_sessionmaker:

        mock_session = MagicMock()
        mock_sessionmaker.return_value.return_value = mock_session

        result = get_db_session()

        assert result == mock_session


def test_sessionmaker_bound_to_engine():
    with patch.dict(os.environ, {
        'DB_PASSWORD': 'secret',
        'DB_HOST':     'localhost'
    }, clear=True), \
    patch('loadCSV.create_engine') as mock_engine, \
    patch('loadCSV.sessionmaker') as mock_sessionmaker:

        mock_engine_instance = MagicMock()
        mock_engine.return_value = mock_engine_instance

        get_db_session()

        mock_sessionmaker.assert_called_once_with(bind=mock_engine_instance)


def test_db_url_format():
    with patch.dict(os.environ, {
        'DB_USER':     'user',
        'DB_PASSWORD': 'pass',
        'DB_HOST':     'host',
        'DB_NAME':     'db',
        'DB_OPTIONS':  'sslmode=disable'
    }), \
    patch('loadCSV.create_engine') as mock_engine, \
    patch('loadCSV.sessionmaker'):

        get_db_session()

        call_url = mock_engine.call_args[0][0]
        assert call_url == 'postgresql://user:pass@host/db?sslmode=disable'